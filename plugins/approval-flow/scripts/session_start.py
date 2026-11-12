"""SessionStart hook: save the plugin's settings for ask-approval and brief Claude.

Claude Code hands the settings the editor typed at install (API key, phone numbers, name) to
HOOKS only, not to commands Claude runs in the shell. This hook saves them privately
(mode 600) so ask-approval can use them, then adds the working rules to Claude's context.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

RULE = ("During video editing, for any creative or irreversible decision (cut choices, deleting footage, "
        "overwriting files, exporting final, changing style), run ask-approval and wait for my keypad answer "
        "before continuing. Do not call for trivial choices. Keep each question under 20 seconds when spoken, "
        "and give at most 3 options.")

HYPERFRAMES = """HyperFrames projects (HTML compositions rendered with `npx hyperframes render`):
- Previews: always render with `-o` and a NEW non-final name, e.g. `npx hyperframes render -o preview-3.mp4`. Previews need no call.
- Needs the approver's OK first: the final render (any output named final, export, master, deliver), `hyperframes publish` / `share`, cloud (Lambda) renders, `normalize-audio --write`, deleting footage, assets or compositions, overwriting an existing render.
- Creative decisions in the composition HTML (cuts and pacing, palette, fonts, layout, music, style changes) also need the approver's OK before you apply them. Routine fixes (lint errors, typos, timing bugs that change nothing visible) do not.
- Always run `npx hyperframes lint` before rendering."""


def phone_context(root):
    return f"""PHONE APPROVAL IS ON (plugin approval-flow).

{RULE}
("my keypad answer" = the approver's, the person whose phone rings.)

How to ask: run  ask-approval "<question>" "<option 1>" "<option 2>" "<option 3>"
(if the command is not found, run: sh "{root}/scripts/run.sh" ask_approval.py ... with the same arguments)
- Option 1 is ALWAYS the action you intend to take. Options 2 and 3 are alternatives or a decline. Only pressing 1 unlocks the approval gate.
- The approver cannot see the screen: say what and which file in plain words. One decision per call.
- Result is one JSON line. exit 0 + "approved": true -> do the action now. exit 0 + "approved": false -> do NOT do it; take the alternative they chose, or continue in the chat.
- exit 2 (no answer / could not connect), 3 (approver's quiet hours), 4 (hourly call budget used), 5 (calls switched off) -> stop and ask the user in the chat. Never guess.
- A hook (approval gate) blocks risky commands until the approver has pressed 1; one approval unlocks exactly one command for 15 minutes. If a command is blocked, run ask-approval, then retry. Never try to get around the gate, and never read or write the approval folder or saved credentials.

{HYPERFRAMES}"""


def chat_context(why):
    return f"""PHONE APPROVAL IS OFF ({why}). Do not try to phone anyone.

{RULE}
("my keypad answer" = the user's answer.) Until phone approval is switched on, ask the user in the chat
instead and wait for their reply before any creative or irreversible decision. Keep each question short and give at most 3 options.

{HYPERFRAMES}"""


def main():
    values = {dest: os.environ.get("CLAUDE_PLUGIN_OPTION_" + src, "").strip() for src, dest in C.OPTION_TO_ENV.items()}
    if values.get("BIRD_API_KEY"):
        try:
            C.write_runtime_env(values)
        except OSError as e:
            print(f"approval-flow: could not save settings: {e}", file=sys.stderr)
    C.load_runtime_env()
    root = str(C.PLUGIN_ROOT)
    needed = ("BIRD_API_KEY", "BIRD_CALLER_ID", "APPROVAL_PHONE")
    missing = [n for n in needed if not os.environ.get(n)]
    if missing:
        ctx = chat_context("approval-flow is not set up yet on this computer: tell the user to run /approval-flow:doctor")
    elif not C.calls_enabled():
        ctx = chat_context("the admin has not switched calls on yet")
    else:
        ctx = phone_context(root)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}))


if __name__ == "__main__":
    main()
