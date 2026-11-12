"""approval-gate: Claude Code PreToolUse hook (matcher: Bash|Write|Edit|Read).

Blocks risky or irreversible actions during video editing unless the approver has just
pressed an approving key on an ask-approval call. One approval unlocks exactly ONE command
and expires after the policy's grant_ttl_s seconds (default 900).

While phone approval is switched off (policy.json calls_enabled=false) the gate never blocks;
it only reminds Claude to ask in the chat.

It also protects the saved Bird credentials and the approval state: Claude cannot read the
credentials or forge an approval.

This is a guard rail against accidents, not a security boundary: the heuristics can be
sidestepped (for example by deleting through a script).

Hook protocol: reads the tool call as JSON on stdin; to block, prints a PreToolUse
permissionDecision "deny" with a reason. Printing nothing and exiting 0 allows the call.
"""
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

TMP_ROOTS = (Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())

AV_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mxf", ".mts", ".wav", ".mp3", ".aac",
          ".flac", ".aiff", ".m4a"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".lottie"}
PROJECT_EXT = {".prproj", ".drp", ".fcpxml", ".fcpbundle", ".aep", ".edl", ".xml", ".srt", ".vtt"}
ASSET_EXT = AV_EXT | IMAGE_EXT | PROJECT_EXT
DELETE_EXT = ASSET_EXT | {".html"}        # deleting a Hyperframes composition is irreversible too
OVERWRITE_EXT = AV_EXT | PROJECT_EXT      # editing .html compositions is normal work, not gated
EXPORT_WORDS = re.compile(r"(final|export|master|render|deliver)", re.I)
READ_ONLY_CMDS = {"cat", "ls", "head", "tail", "jq", "grep", "wc", "stat", "less"}
ENCODERS = {"ffmpeg", "avconv", "handbrakecli", "melt", "auto-editor"}
WRAPPERS = {"sudo", "command", "env", "time", "nice", "nohup", "exec"}
SCRIPT_RUNNERS = {"npm", "pnpm", "yarn", "bun"}
EXPORT_SCRIPTS = re.compile(r"^(render|export|publish|deploy|share|build:video)", re.I)


def decide(allow=True, reason="", context=""):
    if allow:
        if context:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                     "permissionDecision": "allow",
                                                     "permissionDecisionReason": context,
                                                     "additionalContext": context}}))
        sys.exit(0)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def ext_in(token, exts):
    return Path(token.strip("'\"")).suffix.lower() in exts


def under_tmp(token):
    try:
        p = Path(token).expanduser()
        p = (p if p.is_absolute() else Path.cwd() / p).resolve()
    except (OSError, RuntimeError):
        return False
    return any(p == t or t in p.parents for t in TMP_ROOTS)


def positional(tokens):
    return [t for t in tokens[1:] if not t.startswith("-")]


def option_value(args, short, long):
    """Value of -o file / -ofile / --output file / --output=file, or None."""
    for i, t in enumerate(args):
        if t == short or t == long:
            return args[i + 1] if i + 1 < len(args) else ""
        if t.startswith(long + "="):
            return t.split("=", 1)[1]
        if t.startswith(short) and len(t) > 2 and not t.startswith("--"):
            return t[2:]
    return None


def hyperframes_reasons(tokens):
    """Rules for the HyperFrames CLI (npx hyperframes ..., hyperframes ..., npm run render)."""
    out = []
    names = [os.path.basename(t).lower() for t in tokens]
    if any("@hyperframes/aws-lambda" in t.lower() for t in tokens):   # basename() would drop the scope
        out.append("HyperFrames cloud (Lambda) rendering costs money")
    idx = next((i for i, n in enumerate(names) if n in ("hyperframes", "hyperframes.cmd") or n.startswith("hyperframes@")), None)
    if idx is not None:
        rest = tokens[idx + 1:]
        sub = next((t for t in rest if not t.startswith("-")), None)
        if sub in ("publish", "share"):
            out.append("hyperframes publish/share uploads the project to HeyGen (--public makes it visible to anyone)")
        elif sub == "normalize-audio" and "--write" in rest:
            out.append("normalize-audio --write changes the audio levels in the composition")
        elif sub == "lambda":
            out.append("HyperFrames cloud (Lambda) rendering costs money")
        elif sub == "render":
            output = option_value(rest, "-o", "--output")
            if output is None:
                out.append("hyperframes render without -o writes to a default location and may overwrite an "
                           "earlier render (add -o with a new preview filename, for example -o preview-1.mp4)")
            elif output and Path(output).is_file():
                out.append("hyperframes render would overwrite an existing file")
            if output and EXPORT_WORDS.search(Path(output).name):
                out.append("looks like exporting a final/master file")
    if names and names[0] in SCRIPT_RUNNERS:
        script = next((t for t in tokens[1:] if t not in ("run", "run-script") and not t.startswith("-")), "")
        if "run" in tokens[1:3] or names[0] in ("yarn", "bun", "pnpm"):
            if EXPORT_SCRIPTS.match(script or ""):
                out.append(f"project script '{script}' renders, exports or publishes")
    return out


def segment_reasons(tokens):
    """Reasons this single simple command is risky (empty list = fine)."""
    while tokens and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]) or tokens[0] in WRAPPERS):
        tokens = tokens[1:]
    if not tokens:
        return []
    cmd = os.path.basename(tokens[0]).lower()
    args = tokens[1:]
    flags = [t for t in args if t.startswith("-")]
    pos = positional(tokens)
    out = hyperframes_reasons(tokens)

    if cmd in {"rm", "unlink", "shred", "trash", "trash-put", "rmdir"}:
        recursive = any(f in ("-r", "-R", "--recursive") or (not f.startswith("--") and ("r" in f[1:] or "R" in f[1:]))
                        for f in flags)
        if any(ext_in(t, DELETE_EXT) for t in pos):
            out.append("deletes a media, asset, project or composition file")
        elif (recursive or any("*" in t for t in pos)) and not all(under_tmp(t) for t in pos):
            out.append("recursively deletes files outside a temp directory")
    elif cmd == "find" and ("-delete" in args or ("-exec" in args and any(os.path.basename(t) == "rm" for t in args))):
        out.append("find that deletes files")
    elif cmd in {"mv", "cp", "install", "ln"} and len(pos) >= 2:
        if "-n" not in flags and "--no-clobber" not in flags and "-i" not in flags:
            dest = Path(pos[-1])
            targets = [dest / Path(s).name if dest.is_dir() else dest for s in pos[:-1]]
            if any(t.is_file() and not under_tmp(str(t)) for t in targets):
                out.append(f"{cmd} would overwrite an existing file")
    elif cmd == "rsync" and any(f.startswith("--delete") for f in flags):
        out.append("rsync --delete removes files at the destination")
    elif cmd == "dd" and any(t.startswith("of=") for t in args):
        out.append("dd writes raw output over its target")
    elif cmd in {"sed", "perl"} and any(f in ("-i", "-pi", "-ip") or f.startswith("-i") for f in flags) \
            and any(ext_in(t, PROJECT_EXT) for t in pos):
        out.append("in-place edit of a project or caption file")
    elif cmd == "truncate" and any(ext_in(t, ASSET_EXT) for t in pos):
        out.append("truncates a media file")
    elif cmd in ENCODERS:
        output = pos[-1] if pos else ""
        if "-y" in args:
            out.append(f"{cmd} -y overwrites its output without asking")
        elif output and Path(output).is_file():
            out.append("encoder output file already exists")
        if output and EXPORT_WORDS.search(Path(output).name):
            out.append("looks like exporting a final/master file")
    elif cmd == "git" and pos:
        sub, rest = pos[0], args
        if sub == "push" and any(t in ("--force", "-f") or t.startswith("--force-with-lease") for t in rest):
            out.append("force push rewrites remote history")
        elif sub == "reset" and "--hard" in rest:
            out.append("git reset --hard discards work")
        elif sub == "clean" and any(re.fullmatch(r"-[a-zA-Z]*[fd][a-zA-Z]*", t) for t in rest):
            out.append("git clean deletes untracked files")
        elif sub == "branch" and "-D" in rest:
            out.append("force-deletes a branch")
        elif sub == "stash" and any(t in ("drop", "clear") for t in rest):
            out.append("drops stashed work")
        elif sub == "checkout" and ("--" in rest or "." in rest):
            out.append("discards working-tree changes")
        elif sub == "restore" and "--staged" not in rest:
            out.append("discards working-tree changes")
    return out


def command_reasons(command):
    reasons = []
    # Redirect that overwrites a media/project file: > clip.mp4 (but not >>, 2>&1, /dev/null)
    for m in re.finditer(r"(?<![>&0-9])>\s*([^\s;&|>]+)", command):
        target = m.group(1).strip("'\"")
        if target != "/dev/null" and ext_in(target, OVERWRITE_EXT | IMAGE_EXT):
            reasons.append("shell redirect overwrites a media or project file")
    for seg in re.split(r"&&|\|\||;|\||\n", command):
        seg = seg.strip()
        if not seg:
            continue
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        reasons += segment_reasons(tokens)
    return list(dict.fromkeys(reasons))


def protected_bash(command):
    """Reason string if the command touches the saved credentials or approval state, else None."""
    markers = (str(C.APPROVAL_DIR), "runtime.env", ".claude/approval-flow", ".claude\\approval-flow")
    if not any(m in command for m in markers):
        return None
    if "runtime.env" in command:
        return "this would read or change the saved Bird credentials, which must stay private"
    first = os.path.basename(command.strip().split()[0]) if command.strip() else ""
    reading = first in READ_ONLY_CMDS and not re.search(r">|\btee\b|\bsed\s+-i\b", command)
    return None if reading else "this would modify the approval state, which only ask-approval may write"


def inside(path, folder):
    try:
        p = Path(path).expanduser().resolve()
        return p == folder.resolve() or folder.resolve() in p.parents
    except (OSError, RuntimeError):
        return False


def take_grant():
    """Consume the grant if it is fresh and unused. Returns the grant or None."""
    try:
        g = json.loads(C.GRANT_FILE.read_text())
    except (OSError, ValueError):
        return None
    if g.get("consumed") or time.time() - g.get("epoch", 0) > C.setting("grant_ttl_s", int):
        return None
    g["consumed"] = True
    g["used_epoch"] = time.time()
    tmp = C.GRANT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(g))
    os.replace(str(tmp), str(C.GRANT_FILE))
    return g


def run(event):
    tool, ti = event.get("tool_name", ""), event.get("tool_input") or {}
    reasons = []
    if tool == "Bash":
        command = ti.get("command", "")
        why = protected_bash(command)
        if why:
            decide(False, f"Blocked: {why}.")
        reasons = command_reasons(command)
    elif tool == "Read":
        if inside(ti.get("file_path", ""), C.RUNTIME_ENV):
            decide(False, "Blocked: the saved Bird credentials must stay private.")
    elif tool in ("Write", "Edit"):
        path = ti.get("file_path", "")
        if inside(path, C.APPROVAL_DIR):
            decide(False, "Blocked: the approval folder can only be written by ask-approval.")
        if tool == "Write" and Path(path).is_file() and Path(path).suffix.lower() in OVERWRITE_EXT:
            reasons = ["overwrites an existing media or project file"]
    if not reasons:
        decide(True)
    if not C.calls_enabled():
        decide(True, context=("Phone approval is switched off, so the approval gate is not blocking. "
                              "This action normally needs the approver's OK (" + "; ".join(reasons) + "). "
                              "Ask the user in the chat and wait for their answer before doing it."))
    grant = take_grant()
    if grant:
        decide(True, context=(f"Approval {grant['id']} used: approver chose '{grant['option']}' for "
                              f"'{grant['question']}'. This unlocked one risky action ({'; '.join(reasons)})."))
    ttl_min = C.setting("grant_ttl_s", int) // 60
    decide(False, (
        "Blocked by the approval gate: " + "; ".join(reasons) + ". "
        "This is a creative or irreversible action, so the approver must OK it by phone first. "
        "Run ask-approval with the action you intend to take as option 1 (for example: "
        "ask-approval \"Export the final cut?\" \"Export it\" \"Not yet\") and wait. "
        f"If they press 1 this command is unlocked once for {ttl_min} minutes. "
        "If the call cannot connect (exit codes 2, 3, 4 or 5), ask in the chat instead. Never guess."))


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        decide(True)
    try:
        run(event)
    except Exception as e:  # a bug in the gate must never lock the editor out
        print(f"approval-gate: internal error ignored: {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
