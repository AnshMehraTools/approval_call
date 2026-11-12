"""approval-flow doctor: check this computer's setup in plain words.

Never places a call. Never prints a secret. Safe to run any time:
  /approval-flow:doctor        (inside Claude Code)
  approval-doctor [--offline]  (in a terminal)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

E164 = re.compile(r"^\+[1-9]\d{6,14}$")
problems = 0


def say(tag, msg, fix=None):
    global problems
    problems += tag == "FIX"
    print(f"[{tag}] {msg}")
    if fix:
        print(f"       -> {fix}")


def version_of(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip().splitlines()[0]
    except Exception:
        return None


def check_python():
    if sys.version_info < (3, 8):
        say("FIX", f"Python {sys.version.split()[0]} is too old", "install Python 3.8 or newer from python.org")
    else:
        say("OK", f"Python {sys.version.split()[0]}")


def check_settings():
    C.load_runtime_env()
    if not C.RUNTIME_ENV.exists():
        say("FIX", "Your approval settings have not been saved yet",
            "close and reopen Claude Code. If this stays, type /plugin configure approval-flow@approval-flow and fill in the fields")
        return False
    good = True
    key = os.environ.get("BIRD_API_KEY", "")
    if not key:
        say("FIX", "Bird API key is missing", "type /plugin configure approval-flow@approval-flow"); good = False
    elif not key.startswith("bk_"):
        say("FIX", "The Bird API key does not look right (it should start with bk_)", "ask your admin for the key again"); good = False
    else:
        say("OK", "Bird API key is saved (hidden)")
    for env, label in (("APPROVAL_PHONE", "Approver phone number"), ("BIRD_CALLER_ID", "Caller ID number")):
        v = os.environ.get(env, "")
        if not v:
            say("FIX", f"{label} is missing", "type /plugin configure approval-flow@approval-flow"); good = False
        elif not E164.match(v):
            say("FIX", f"{label} must look like +971501234567 (a plus sign, country code, then the number, no spaces)",
                "fix it with /plugin configure approval-flow@approval-flow"); good = False
        else:
            say("OK", f"{label} is saved ({v[:3]}...{v[-2:]})")
    if os.environ.get("EDITOR_NAME"):
        say("OK", f"Your name for the approver: {os.environ['EDITOR_NAME']}")
    else:
        say("WARN", "No editor name set, so the approver will hear a generic intro",
            "add your first name with /plugin configure approval-flow@approval-flow")
    if not os.environ.get("BIRD_API_URL"):
        say("FIX", "Bird API URL is missing", "use the default https://us1.platform.bird.com"); good = False
    return good


def check_mode():
    p = C.policy()
    if not p.get("calls_enabled"):
        say("INFO", "Phone calls are switched OFF by your admin for now. Claude will ask you in the chat instead. This is expected until rollout.")
    elif os.environ.get("APPROVAL_CALLS", "on").lower() == "off":
        say("INFO", "Phone calls are switched off on this computer (APPROVAL_CALLS=off)")
    else:
        say("OK", "Phone calls are switched ON")
    now = C.approver_now()
    quiet = C.in_quiet_hours(now)
    say("INFO", f"Approver's local time is {now.strftime('%H:%M')} ({C.setting('approver_timezone')}); "
                f"quiet hours {C.setting('quiet_hours')}: {'quiet right now, no calls' if quiet else 'calls allowed now'}")


def check_bird():
    s, d = C.api("GET", "/v1/voice/settings", retries=1)
    if s != 200:
        say("FIX", f"Bird did not accept the API key (HTTP {s})", "ask your admin for a new key, then type /plugin configure approval-flow@approval-flow")
        return
    left = ((d.get("daily_spend_limit") or {}).get("remaining") or {}).get("amount")
    say("OK", "Bird accepted the API key" + (f" (daily spend left: ${left})" if left is not None else ""))

    caller = os.environ.get("BIRD_CALLER_ID", "")
    s, d = C.api("GET", "/v1/voice/verified-numbers", retries=1)
    found = None
    if s == 200:
        found = next((n for n in d.get("data", []) if n.get("phone_number") == caller), None)
    if found and found.get("status") == "verified" and found.get("outbound_enabled"):
        say("OK", "Caller ID is verified in Bird and allowed to call out")
    elif found:
        say("FIX", f"Caller ID is registered but not ready (status {found.get('status')})", "your admin must finish verifying it in Bird")
    else:
        s2, d2 = C.api("GET", "/v1/voice/numbers", retries=1)
        owned = s2 == 200 and any(n.get("phone_number") == caller for n in d2.get("data", []))
        if owned:
            say("OK", "Caller ID is a number owned in Bird")
        else:
            say("FIX", "Caller ID is not registered in Bird", "check the number, or ask your admin to verify it in Bird")

    phone = os.environ.get("APPROVAL_PHONE", "").lstrip("+")
    s, d = C.api("GET", "/v1/voice/destinations", retries=1)
    if s == 200 and phone:
        matches = [r for r in d.get("data", []) if phone.startswith(str(r.get("dial_code", "x")))]
        if matches:
            best = max(len(str(r["dial_code"])) for r in matches)
            cands = [r for r in matches if len(str(r["dial_code"])) == best]
            names = "/".join(r["country_name"] for r in cands)
            if any(r.get("enabled") for r in cands):
                say("OK", f"Calling {names} is enabled in Bird")
            else:
                say("FIX", f"Calling {names} is not enabled in Bird", "your admin must turn it on in Bird: Voice, then Destinations")


def check_gate():
    gate = Path(__file__).resolve().parent / "approval_gate.py"
    with tempfile.TemporaryDirectory() as d:
        pol = Path(d, "policy.json")
        pol.write_text(json.dumps({"calls_enabled": True}))
        env = {**os.environ, "APPROVAL_HOME": str(Path(d, "state")), "APPROVAL_POLICY_FILE": str(pol)}
        env.pop("APPROVAL_CALLS", None)

        def decision(cmd):
            p = subprocess.run([sys.executable, str(gate)], capture_output=True, text=True, cwd=d, env=env,
                               input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}))
            if p.returncode != 0:
                return "error"
            return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout.strip() else "allow"

        ok = decision("ls") == "allow" and decision("rm clip.mp4") == "deny" \
            and decision("npx hyperframes render -o final.mp4") == "deny" \
            and decision("npx hyperframes render -o preview-1.mp4") == "allow" \
            and decision("cat ~/.claude/approval-flow/runtime.env") == "deny"
    if ok:
        say("OK", "Safety gate works (blocks deleting footage and final exports until approved; previews are fine)")
    else:
        say("FIX", "The safety gate did not behave as expected", "reinstall the plugin: /plugin, then update approval-flow, and restart Claude Code")


def check_tools():
    node = version_of(["node", "--version"])
    if node and int(node.lstrip("v").split(".")[0]) >= 22:
        say("OK", f"Node.js {node} (needed by Hyperframes)")
    elif node:
        say("WARN", f"Node.js {node} is older than 22, which Hyperframes needs", "update Node.js")
    else:
        say("WARN", "Node.js was not found (Hyperframes needs version 22 or newer)", "install it from nodejs.org")
    say("OK" if shutil.which("ffmpeg") else "WARN", "FFmpeg found (needed by Hyperframes)" if shutil.which("ffmpeg")
        else "FFmpeg was not found (Hyperframes needs it)")


def main():
    offline = "--offline" in sys.argv
    print("approval-flow check (no calls are made, nothing secret is shown)\n")
    check_python()
    configured = check_settings()
    check_mode()
    if configured and not offline:
        check_bird()
    elif not configured:
        say("INFO", "Skipping the Bird checks until the settings above are fixed")
    check_gate()
    check_tools()
    print()
    if problems:
        print(f"{problems} thing(s) to fix. Fix the [FIX] lines above, restart Claude Code, then run this check again.")
        sys.exit(1)
    print("All good. You are set up.")


if __name__ == "__main__":
    main()
