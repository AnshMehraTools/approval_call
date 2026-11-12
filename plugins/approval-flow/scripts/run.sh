#!/bin/sh
# Finds a working Python 3 and runs one of this folder's scripts with it.
# Usage: run.sh <script.py> [args...]
script="$1"
shift
dir=$(cd "$(dirname "$0")" && pwd)
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
    PYTHONDONTWRITEBYTECODE=1 exec "$py" "$dir/$script" "$@"
  fi
done
echo "approval-flow: Python 3 was not found. Install it from https://www.python.org/downloads/ and restart Claude Code." >&2
exit 2
