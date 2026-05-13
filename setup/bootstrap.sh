#!/usr/bin/env bash
# Thin shim that finds python3 and forwards to bootstrap.py.
# Use this if you don't want to type `python3 setup/bootstrap.py ...`.

set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed or not in PATH." >&2
  echo "Install Python 3.9+ from https://python.org and re-run." >&2
  exit 1
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/bootstrap.py" "$@"
