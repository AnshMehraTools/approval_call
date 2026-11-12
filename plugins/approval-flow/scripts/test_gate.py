"""Offline tests for approval-flow. Places no calls, uses a throwaway folder, never touches the
real approval folder, and points the Bird address at a dead port so nothing can leave the machine.

  python3 plugins/approval-flow/scripts/test_gate.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
GATE, ASK, START, DOCTOR = (SCRIPTS / n for n in ("approval_gate.py", "ask_approval.py", "session_start.py", "doctor.py"))
fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {got}" + ("" if ok else f" (wanted {want})"))


def run(script, args=(), env=None, cwd=None, stdin=None):
    return subprocess.run([sys.executable, str(script), *args], input=stdin, capture_output=True, text=True,
                          cwd=cwd, env=env)


# The gate ignores scratch files under /tmp on purpose, so the test project lives in a local .tmp folder.
SCRATCH = SCRIPTS.parent.parent.parent / ".tmp"
SCRATCH.mkdir(exist_ok=True)

with tempfile.TemporaryDirectory(dir=str(SCRATCH)) as d:
    d = Path(d).resolve()
    work, home = d / "work", d / "home"
    work.mkdir()
    for f in ("clip.mp4", "b.txt", "a.txt", "out.mp4", "index.html", "logo.png"):
        (work / f).write_text("x")
    on_policy, off_policy = d / "on.json", d / "off.json"
    on_policy.write_text(json.dumps({"calls_enabled": True}))
    off_policy.write_text(json.dumps({"calls_enabled": False}))
    grant = home / "grant.json"

    def env(policy=on_policy, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("APPROVAL_", "BIRD_", "CLAUDE_PLUGIN_OPTION_"))}
        e.update(APPROVAL_HOME=str(home), APPROVAL_POLICY_FILE=str(policy), BIRD_API_URL="http://127.0.0.1:9", **extra)
        return e

    def gate(tool_input, tool="Bash", policy=on_policy):
        p = run(GATE, env=env(policy), cwd=str(work), stdin=json.dumps({"tool_name": tool, "tool_input": tool_input}))
        assert p.returncode == 0, p.stderr
        out = json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else {}
        return out.get("permissionDecision", "allow"), out

    cmd = lambda c, **k: gate({"command": c}, **k)

    print("-- allowed without approval")
    for c in ["ls -la", "git status", "git commit -m 'x'", "git push origin main", "rm -f /tmp/scratch.txt",
              "rm -rf /tmp/some/dir", "cp a.txt new.txt", "ffmpeg -i clip.mp4 preview.mp4", "ask-approval 'Q?' 'Yes' 'No'",
              "echo hi > notes.txt", "ls | head -3 && echo done",
              "npx hyperframes lint", "npx hyperframes preview", "npx hyperframes init demo",
              "npx hyperframes add data-chart", "npx hyperframes render -o preview-1.mp4",
              "npx hyperframes render --output=preview-2.mp4", "hyperframes render -c index.html -o preview-3.mp4",
              "npx hyperframes normalize-audio --reference a.wav --target b.wav",
              "npm run lint", "npm run dev", "npx hyperframes doctor"]:
        check(c, cmd(c)[0], "allow")

    print("-- blocked without approval")
    for c in ["rm clip.mp4", "rm -rf footage", "rm -r ./raw", "rm index.html", "rm assets/logo.png",
              "find . -name '*.mov' -delete", "cp a.txt b.txt", "mv a.txt b.txt", "ffmpeg -y -i clip.mp4 x.mp4",
              "ffmpeg -i clip.mp4 final_cut.mp4", "ffmpeg -i a.mp4 clip.mp4", "git push --force origin main",
              "git reset --hard HEAD~1", "git clean -fd", "echo x > timeline.mp4", "sed -i 's/a/b/' captions.srt",
              "ls && rm clip.mp4", "dd if=/dev/zero of=clip.mp4", "rsync -a --delete src/ dst/",
              "npx hyperframes render", "npx hyperframes render -o final.mp4", "npx hyperframes render -o master-v2.mp4",
              "npx hyperframes render -c index.html -o out.mp4", "npx hyperframes publish",
              "npx hyperframes publish --public --yes", "npx hyperframes share", "npx hyperframes share --update",
              "npx hyperframes normalize-audio --write --reference a.wav --target b.wav",
              "npx @hyperframes/aws-lambda deploy", "npx hyperframes lambda render",
              "npm run render", "pnpm export", "yarn publish"]:
        check(c, cmd(c)[0], "deny")

    print("-- Write tool")
    check("Write new file", gate({"file_path": str(work / "new.html")}, tool="Write")[0], "allow")
    check("Write over existing composition (normal editing)", gate({"file_path": str(work / "index.html")}, tool="Write")[0], "allow")
    check("Write over existing .mp4", gate({"file_path": str(work / "clip.mp4")}, tool="Write")[0], "deny")

    print("-- credentials and approval state are protected, grant or not")
    home.mkdir()
    (home / "runtime.env").write_text("BIRD_API_KEY=bk_test\n")
    grant.write_text(json.dumps({"id": "t", "epoch": time.time(), "question": "q", "option": "o", "consumed": False}))
    for c in [f"cat {home}/runtime.env", "cat ~/.claude/approval-flow/runtime.env", f"echo '{{}}' > {home}/grant.json",
              f"python3 -c \"open('{home}/grant.json','w')\"", f"rm {home}/grant.json", f"cp /dev/null {home}/log.jsonl"]:
        check(c, cmd(c)[0], "deny")
    check("reading the audit log is fine", cmd(f"cat {home}/log.jsonl")[0], "allow")
    check("Read runtime.env", gate({"file_path": str(home / "runtime.env")}, tool="Read")[0], "deny")
    check("Read an ordinary file", gate({"file_path": str(work / "a.txt")}, tool="Read")[0], "allow")
    check("Write into approval folder", gate({"file_path": str(grant)}, tool="Write")[0], "deny")
    check("Edit in approval folder", gate({"file_path": str(grant)}, tool="Edit")[0], "deny")

    print("-- one grant unlocks exactly one command")
    grant.write_text(json.dumps({"id": "g1", "epoch": time.time(), "question": "Delete clip?", "option": "Delete it", "consumed": False}))
    check("risky command with fresh grant", cmd("rm clip.mp4")[0], "allow")
    check("same grant used again", cmd("rm clip.mp4")[0], "deny")
    grant.write_text(json.dumps({"id": "g2", "epoch": time.time() - 3600, "question": "q", "option": "o", "consumed": False}))
    check("1h-old grant is expired", cmd("rm clip.mp4")[0], "deny")
    grant.unlink()
    check("no grant at all", cmd("rm clip.mp4")[0], "deny")

    print("-- phone approval switched off: never blocks, but tells Claude to ask in chat")
    dec, out = cmd("npx hyperframes render -o final.mp4", policy=off_policy)
    check("final render allowed while off", dec, "allow")
    check("...with a reminder to ask in chat", "Ask the user in the chat" in out.get("additionalContext", ""), True)
    check("harmless command stays silent while off", cmd("ls", policy=off_policy)[1], {})

    print("-- session start briefing")
    opts = {"CLAUDE_PLUGIN_OPTION_BIRD_API_KEY": "bk_fake_secret_value", "CLAUDE_PLUGIN_OPTION_APPROVER_PHONE": "+971500000000",
            "CLAUDE_PLUGIN_OPTION_BIRD_CALLER_ID": "+911111111111", "CLAUDE_PLUGIN_OPTION_EDITOR_NAME": "Priya",
            "CLAUDE_PLUGIN_OPTION_BIRD_API_URL": "http://127.0.0.1:9"}
    ctx = lambda p, **x: json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"]
    p = run(START, env=env(on_policy))
    check("not configured -> chat mode", "set up yet" in ctx(p), True)
    p = run(START, env=env(off_policy, **opts))
    check("configured but calls off -> chat mode", "PHONE APPROVAL IS OFF" in ctx(p) and "admin has not switched calls on" in ctx(p), True)
    check("settings saved privately", (home / "runtime.env").read_text().count("=") >= 4, True)
    if os.name == "posix":
        check("runtime.env is mode 600", oct((home / "runtime.env").stat().st_mode & 0o777), "0o600")
    check("secret never appears in Claude's briefing", "bk_fake_secret_value" not in p.stdout, True)
    p = run(START, env=env(on_policy))
    check("calls on -> phone mode, rule included", "PHONE APPROVAL IS ON" in ctx(p) and "creative or irreversible decision" in ctx(p), True)
    check("Hyperframes guidance included", "hyperframes render -o" in ctx(p), True)

    print("-- ask-approval guard rails (no calls are placed)")
    dry = run(ASK, ["--dry-run", "Export the final cut?", "Export it", "Not yet"], env=env(on_policy))
    spoken = [n["input"].get("text") or n["input"]["prompts"][0]["text"]
              for n in json.loads(dry.stdout)["sequence"]["definition"]["nodes"] if n["id"] in ("ask", "pick")]
    check("spoken intro names the editor", spoken[0].startswith("Approval request from Priya's video edit. Export"), True)
    check("menu is spoken", spoken[1], "Press 1 for export it, press 2 for not yet.")
    long_q = " ".join(["word"] * 60)
    check("too-long question refused", run(ASK, [long_q, "A", "B"], env=env(on_policy)).returncode, 1)
    check("4 options refused", run(ASK, ["Q?", "A", "B", "C", "D"], env=env(on_policy)).returncode, 1)
    check("calls off -> exit 5", run(ASK, ["Q?", "A", "B"], env=env(off_policy)).returncode, 5)
    check("local kill switch -> exit 5", run(ASK, ["Q?", "A", "B"], env=env(on_policy, APPROVAL_CALLS="off")).returncode, 5)
    quiet = run(ASK, ["Q?", "A", "B"], env=env(on_policy, APPROVAL_QUIET_HOURS="0-23"))
    check("quiet hours -> exit 3", (quiet.returncode, json.loads(quiet.stdout)["reason"]), (3, "quiet_hours"))
    budget = run(ASK, ["Q?", "A", "B"], env=env(on_policy, APPROVAL_MAX_PER_HOUR="0", APPROVAL_QUIET_HOURS=""))
    check("budget used -> exit 4", (budget.returncode, json.loads(budget.stdout)["reason"]), (4, "hourly_call_budget_used"))

    print("-- doctor (offline)")
    p = run(DOCTOR, ["--offline"], env=env(on_policy, **opts))
    check("doctor passes the gate self-test", "Safety gate works" in p.stdout, True)
    check("doctor never prints the key", "bk_fake_secret_value" not in p.stdout, True)
    check("doctor masks phone numbers", "+971500000000" not in p.stdout, True)

print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
