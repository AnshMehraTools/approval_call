"""Shared paths, policy, secrets and Bird API access for the approval-flow scripts."""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# Everything private lives here, outside any project: saved credentials, the one-time
# approval grant and the audit log. (APPROVAL_HOME overrides it, used by the tests.)
APPROVAL_DIR = Path(os.environ.get("APPROVAL_HOME") or (Path.home() / ".claude" / "approval-flow"))
RUNTIME_ENV = APPROVAL_DIR / "runtime.env"
GRANT_FILE = APPROVAL_DIR / "grant.json"
LOG_FILE = APPROVAL_DIR / "log.jsonl"

# Central policy, shipped in the plugin (policy.json). The admin changes it and publishes an update.
POLICY_DEFAULTS = {
    "calls_enabled": False,
    "approver_timezone": "Asia/Dubai",
    "quiet_hours": "22-07",
    "max_per_hour": 4,
    "grant_ttl_s": 900,
    "approve_digits": "1",
    "intro_template": "Approval request from {editor}'s video edit.",
    "intro_fallback": "Approval request from your video editing assistant.",
}

# Plugin settings (userConfig keys, upper-cased) -> names written to runtime.env
OPTION_TO_ENV = {
    "BIRD_API_KEY": "BIRD_API_KEY",
    "BIRD_API_URL": "BIRD_API_URL",
    "BIRD_CALLER_ID": "BIRD_CALLER_ID",
    "APPROVER_PHONE": "APPROVAL_PHONE",
    "EDITOR_NAME": "EDITOR_NAME",
}


def die(msg, code=1):
    print(f"approval-flow: {msg}", file=sys.stderr)
    sys.exit(code)


def policy():
    p = dict(POLICY_DEFAULTS)
    path = Path(os.environ.get("APPROVAL_POLICY_FILE") or (PLUGIN_ROOT / "policy.json"))
    try:
        p.update(json.loads(path.read_text()))
    except (OSError, ValueError):
        pass
    return p


def setting(name, cast=str):
    """Environment variable APPROVAL_<NAME> beats policy.json beats the built-in default."""
    v = os.environ.get("APPROVAL_" + name.upper())
    return cast(v) if v not in (None, "") else cast(policy()[name])


def calls_enabled():
    """True only if the admin switched calls on (policy.json) and the user has not turned them off."""
    return bool(policy().get("calls_enabled")) and os.environ.get("APPROVAL_CALLS", "on").lower() != "off"


def load_runtime_env():
    try:
        text = RUNTIME_ENV.read_text()
    except OSError:
        return
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def write_runtime_env(values):
    """Save credentials privately (mode 600). Returns True if the file changed."""
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k}={str(v).replace(chr(10), ' ').strip()}\n" for k, v in values.items() if v)
    try:
        if RUNTIME_ENV.read_text() == body:
            return False
    except OSError:
        pass
    tmp = RUNTIME_ENV.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.replace(str(tmp), str(RUNTIME_ENV))
    return True


def require(name):
    v = os.environ.get(name)
    if not v:
        die(f"{name} is not set. Run /approval-flow:doctor to see what is missing.")
    return v


def approver_now():
    tzname = setting("approver_timezone")
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tzname))
    except Exception:
        if tzname == "Asia/Dubai":  # no time-zone database installed: Dubai has no DST, fixed UTC+4
            return datetime.now(timezone(timedelta(hours=4)))
        die(f"cannot resolve time zone {tzname!r}; install tzdata or use Asia/Dubai")


def in_quiet_hours(now):
    spec = setting("quiet_hours").strip()
    if not spec:
        return False
    try:
        start, end = (int(x) for x in spec.split("-"))
    except ValueError:
        die(f"quiet_hours must look like 22-07, got {spec!r}")
    h = now.hour
    return (h >= start or h < end) if start > end else (start <= h < end)


def api(method, path, body=None, idem_key=None, retries=3):
    """HTTP call to Bird. Retries only transient errors, reusing the same bytes and key."""
    url = require("BIRD_API_URL").rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + require("BIRD_API_KEY"), "Content-Type": "application/json"}
    if idem_key:
        headers["Idempotency-Key"] = idem_key
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            payload = e.read().decode(errors="replace")[:2000]
            if e.code in (425, 429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                last = (e.code, payload)
                continue
            return e.code, payload
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                last = (0, str(e))
                continue
            return 0, str(e)
    return last
