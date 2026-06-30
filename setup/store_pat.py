#!/usr/bin/env python3
"""
store_pat.py — store the Talend Management Console PAT in talend.local.properties.

Reads the token via `getpass` (no terminal echo), so it doesn't end up in your
shell history or visible during screen-share. Writes it to
`<project>/.claude/talend.local.properties` under key `tmc.pat`.

Usage:
    store_pat.py <absolute-path-to-talend-project>

If the file already has a `tmc.pat` value, it's overwritten (we don't keep old
secrets around). The file is created from the template if it doesn't exist.

A future version will store the token in your OS keychain instead. The UX
won't change: Claude will retrieve it transparently.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
import properties  # noqa: E402

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def main(argv: list[str]) -> int:
    # Windows consoles default to cp1252, which can't encode some characters
    # this script prints. Force UTF-8 so it doesn't crash mid-output;
    # replace-on-error means a truly hopeless codec still prints something
    # instead of raising.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    p = argparse.ArgumentParser(prog="store_pat.py", description=__doc__)
    p.add_argument("project", help="absolute path to your Talend project")
    args = p.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"{RED}[FAIL]{RESET}  not a directory: {project}", file=sys.stderr)
        return 1

    local_cfg = project / ".claude" / "talend.local.properties"
    if not local_cfg.exists():
        template = REPO_ROOT / "templates" / "talend.local.properties.example"
        local_cfg.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, local_cfg)

    print(f"Storing TMC PAT in {local_cfg}")
    print(f"{DIM}        (input is hidden — paste your token and press Enter){RESET}")

    try:
        token = getpass.getpass("TMC PAT: ")
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"{YELLOW}Cancelled.{RESET}")
        return 1

    token = token.strip()
    if not token:
        print(f"{YELLOW}Empty input — nothing changed.{RESET}")
        return 1

    if len(token) < 20:
        print(f"{YELLOW}[WARN]{RESET} that looks short for a Talend PAT — proceeding anyway.")

    properties.set_value(local_cfg, "tmc.pat", token)

    # Best-effort chmod 600 (Unix only).
    if not sys.platform == "win32":
        try:
            os.chmod(local_cfg, 0o600)
        except OSError:
            pass

    print(f"{GREEN}[OK]{RESET}    PAT stored.")
    print(f"{DIM}        Run setup/doctor.py {project} to verify.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
