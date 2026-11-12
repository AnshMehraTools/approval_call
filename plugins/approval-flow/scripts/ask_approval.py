"""ask-approval: phone the approver, read a question, and return the key they press.

Usage:
  ask-approval "Export the final cut as MP4?" "Export it" "Not yet" "Something else"
  ask-approval --dry-run "Question?" "Yes" "No"

Options are mapped to keys 1..N in the order given (max 3).
CONVENTION: option 1 is always the action Claude intends to take. Only pressing a key in
the policy's approve_digits (default "1") records a grant that unlocks ONE risky command in
the approval gate. Other keys are alternatives or a decline.

Output (stdout, one JSON line):
  {"answered": true,  "digit": "1", "option": "Export it", "approved": true, "attempts": 1}
  {"answered": false, "reason": "answered_but_initial_timeout", "attempts": 2}

Exit codes:
  0  approver pressed a valid key (check "approved": option 1 vs an alternative)
  1  setup or API error (message on stderr)
  2  no usable answer after one re-ask -> ask in the chat instead of guessing
  3  quiet hours for the approver, no call placed -> ask in the chat / wait
  4  call budget for this hour used up, no call placed -> ask in the chat
  5  phone approval is switched off (admin policy or APPROVAL_CALLS=off) -> ask in the chat

Settings: see policy.json (admin) and the plugin settings saved by Claude Code (credentials).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

MAX_ATTEMPTS = 2           # first ask + one re-ask
MAX_OPTIONS = 3
MAX_SPOKEN_WORDS = 50      # ~20 seconds of speech, intro included
ATTEMPT_DEADLINE_S = 120   # give up on one call after ~2 minutes
RINGING_TIMEOUT_S = 45
GATHER_TIMEOUT_S = 10
POLL_S = 3


def intro():
    custom = os.environ.get("APPROVAL_INTRO", "").strip()
    if custom:
        return custom
    editor = re.sub(r"[^\w .'-]", "", os.environ.get("EDITOR_NAME", "")).strip()[:30]
    p = C.policy()
    return p["intro_template"].format(editor=editor) if editor else p["intro_fallback"]


def dials_in_last_hour():
    try:
        lines = C.LOG_FILE.read_text().splitlines()
    except OSError:
        return 0
    cutoff, n = time.time() - 3600, 0
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("dialed") and e.get("epoch", 0) >= cutoff:
            n += 1
    return n


def log_attempt(entry):
    C.APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "epoch": time.time(), **entry}
    with C.LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def write_grant(question, digit, option):
    C.APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = C.GRANT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"id": uuid.uuid4().hex[:12], "epoch": time.time(), "question": question,
                               "digit": digit, "option": option, "consumed": False}))
    os.replace(str(tmp), str(C.GRANT_FILE))


def clear_grant():
    try:
        C.GRANT_FILE.unlink()
    except FileNotFoundError:
        pass


def build_sequence(spoken_question, options):
    """Inline sequence: say(intro + question) -> gather one key -> exit with the choice."""
    menu = ", ".join(f"press {i} for {o}" for i, o in enumerate(options, 1))
    nodes = [
        {"id": "start", "type": "trigger.start_call", "type_version": 1, "config": {}, "input": {},
         "connections": {"event": {"node_id": "ask", "port": "input"}}},
        {"id": "ask", "type": "voice.say", "type_version": 1, "config": {},
         "input": {"text": spoken_question, "language": "en"},
         "connections": {"next": {"node_id": "pick", "port": "input"}}},
    ]
    matches = {f"opt{i}": str(i) for i in range(1, len(options) + 1)}
    connections = {name: {"node_id": f"exit_{name}", "port": "input"} for name in matches}
    connections["timeout"] = {"node_id": "exit_timeout", "port": "input"}
    connections["fallback"] = {"node_id": "exit_invalid", "port": "input"}
    nodes.append({
        "id": "pick", "type": "voice.gather", "type_version": 1, "config": {},
        "input": {
            "prompts": [{"type": "say", "text": menu.capitalize() + ".", "language": "en"}],
            "max_digits": 1,
            "timeout_seconds": GATHER_TIMEOUT_S,
            "inter_digit_timeout_seconds": 2,
            "finish_on_key": None,
            "private": False,  # keep digits in the trace so we can read them
            "matches": matches,
        },
        "connections": connections,
    })
    for name in matches:
        nodes.append({"id": f"exit_{name}", "type": "logic.exit", "type_version": 1,
                      "config": {"status": "succeeded", "reason": name}, "input": {"output": {}}})
    for name in ("timeout", "invalid"):
        nodes.append({"id": f"exit_{name}", "type": "logic.exit", "type_version": 1,
                      "config": {"status": "failed", "reason": name}, "input": {"output": {}}})
    return {"schema_version": 1, "expression_environment": "bird.cel.v1", "nodes": nodes}


def find_choice(trace, options):
    """Read the gather result from the leg trace.

    The gather node's span (data.type == "node", data.node_id == "pick") carries
    data.selected_port ("opt1".."optN", "timeout" or "fallback") and
    data.output {"digits": "...", "reason": "..."}. Returns (digit, option_label) or (None, reason).
    Never search the raw trace text: it embeds the frozen definition, which
    contains every option name.
    """
    for span in trace.get("spans", []):
        d = span.get("data") or {}
        if d.get("type") == "node" and d.get("node_id") == "pick":
            port = d.get("selected_port") or ""
            if port.startswith("opt") and port[3:].isdigit() and 1 <= int(port[3:]) <= len(options):
                return port[3:], options[int(port[3:]) - 1]
            return None, ((d.get("output") or {}).get("reason") or port or "no_valid_key")
    return None, "gather_not_reached"


def one_attempt(spoken_question, options, attempt, run_id, debug_trace=None):
    body = {
        "from": C.require("BIRD_CALLER_ID"),
        "to": C.require("APPROVAL_PHONE"),
        "ringing_timeout_seconds": RINGING_TIMEOUT_S,
        "sequence": {"entry_node_id": "start", "trigger_data": {},
                     "definition": build_sequence(spoken_question, options)},
    }
    # One stable key per intended call: a retry of the same attempt can never double-dial.
    key = hashlib.sha256(f"{run_id}:{attempt}:{spoken_question}:{options}".encode()).hexdigest()[:48]
    status, resp = C.api("POST", "/v1/voice/calls", body, idem_key=key)
    if status not in (200, 202):
        C.die(f"Bird refused the call (HTTP {status}): {resp}")
    leg_id = resp["initial_leg_id"]
    deadline = time.time() + ATTEMPT_DEADLINE_S
    leg = {}
    while time.time() < deadline:
        time.sleep(POLL_S)
        s, leg = C.api("GET", f"/v1/voice/legs/{leg_id}")
        if s == 200 and leg.get("ended_at"):
            break
    else:
        return None, "timed_out_waiting", leg_id
    s, trace = C.api("GET", f"/v1/voice/legs/{leg_id}/trace", retries=6)
    if s != 200:
        return None, f"trace_unavailable_{s}", leg_id
    if debug_trace:
        Path(debug_trace).write_text(json.dumps({"leg": leg, "trace": trace}, indent=2))
    digit, label = find_choice(trace, options)
    if digit is None:
        why = leg.get("rejection_reason") or leg.get("status") or label
        if leg.get("answered_at"):
            why = f"answered_but_{label}"   # e.g. answered_but_initial_timeout
        elif leg.get("sip_response_code"):
            why = f"{why} (SIP {leg['sip_response_code']}, answered={bool(leg.get('answered_at'))})"
        return None, why, leg_id
    return digit, label, leg_id


def main():
    C.load_runtime_env()
    p = argparse.ArgumentParser(description="Phone the approver and return the key pressed.")
    p.add_argument("question")
    p.add_argument("options", nargs="+", help="up to 3 options; option 1 = the action Claude intends")
    p.add_argument("--attempts", type=int, default=MAX_ATTEMPTS, choices=[1, 2],
                   help="1 = never re-dial; default 2 = re-ask once")
    p.add_argument("--dry-run", action="store_true", help="print the request body, place no call")
    p.add_argument("--debug-trace", help="save the raw leg + trace JSON to this file")
    a = p.parse_args()
    if len(a.options) > MAX_OPTIONS:
        C.die(f"at most {MAX_OPTIONS} options")
    spoken_question = f"{intro()} {a.question}".strip()
    words = len((spoken_question + " " + " ".join(a.options)).split())
    if words > MAX_SPOKEN_WORDS:
        C.die(f"too long to speak in ~20s ({words} words > {MAX_SPOKEN_WORDS}, intro included); shorten it")
    if a.dry_run:
        print(json.dumps({"calls_enabled": C.calls_enabled(), "to": "<approver>",
                          "sequence": {"entry_node_id": "start", "trigger_data": {},
                                       "definition": build_sequence(spoken_question, a.options)}}, indent=2))
        return
    if not C.calls_enabled():
        print(json.dumps({"answered": False, "reason": "calls_switched_off", "attempts": 0}))
        sys.exit(5)
    approve = {d.strip() for d in C.setting("approve_digits").split(",") if d.strip()}

    clear_grant()  # a new question supersedes any earlier, unused approval
    now = C.approver_now()
    if C.in_quiet_hours(now):
        print(json.dumps({"answered": False, "reason": "quiet_hours",
                          "approver_local_time": now.strftime("%H:%M"), "attempts": 0}))
        sys.exit(3)
    max_per_hour = C.setting("max_per_hour", int)
    if dials_in_last_hour() + a.attempts > max_per_hour:
        print(json.dumps({"answered": False, "reason": "hourly_call_budget_used",
                          "max_per_hour": max_per_hour, "attempts": 0}))
        sys.exit(4)

    run_id = uuid.uuid4().hex
    reason = "unknown"
    for attempt in range(1, a.attempts + 1):
        digit, label, leg_id = one_attempt(spoken_question, a.options, attempt, run_id, a.debug_trace)
        log_attempt({"dialed": True, "attempt": attempt, "question": a.question, "options": a.options,
                     "answered": bool(digit), "digit": digit, "option": label if digit else None,
                     "reason": None if digit else label, "leg_id": leg_id})
        if digit:
            approved = digit in approve
            if approved:
                write_grant(a.question, digit, label)
            print(json.dumps({"answered": True, "digit": digit, "option": label, "approved": approved,
                              "attempts": attempt, "leg_id": leg_id}))
            return
        reason = label
    print(json.dumps({"answered": False, "reason": reason, "attempts": a.attempts}))
    sys.exit(2)


if __name__ == "__main__":
    main()
