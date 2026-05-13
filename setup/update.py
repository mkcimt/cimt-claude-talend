#!/usr/bin/env python3
"""
update.py — pull the latest cimt-claude-talend; optionally refresh a project.

Two modes:

  update.py
    Just pulls the kit's repo. Reports what changed. Reminds you to re-run
    install.py on consuming projects if templates changed.

  update.py <project-path>
    Pulls, then immediately re-runs install.py on that project so its
    CLAUDE.md integration block, .gitignore, and symlinks are refreshed to
    match the new kit version. This is what Claude calls when the user
    says "update cimt-claude-talend" — `<project-path>` is the project the
    user is currently working in.

If skill or agent files changed, the user needs to restart their Claude Code
session for those to take effect (knowledge files reload automatically).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(prog="update.py", description=__doc__)
    p.add_argument("project", nargs="?", help="if given, run install.py on this project after the pull")
    args = p.parse_args()

    head_before = git(["rev-parse", "HEAD"]).stdout.strip()

    print(f"{BOLD}Updating cimt-claude-talend{RESET}")
    print(f"{DIM}        {REPO_ROOT}{RESET}")

    result = git(["pull", "--ff-only"])
    if result.returncode != 0:
        print(f"{RED}[FAIL]{RESET}  git pull failed:")
        print(result.stderr)
        return 1

    head_after = git(["rev-parse", "HEAD"]).stdout.strip()

    if head_before == head_after:
        print(f"{GREEN}[OK]{RESET}    Already up to date.")
        if args.project is None:
            return 0
        # Even if kit is up-to-date, run install.py on the project (cheap, ensures consistency).

    if head_before != head_after:
        diff = git(["diff", "--name-only", head_before, head_after]).stdout.strip()
        changed = [line for line in diff.splitlines() if line]
        print(f"{GREEN}[OK]{RESET}    Pulled {len(changed)} file change(s).")

        skill_or_agent_changed = any(
            f.startswith("skills/") or f.startswith("agents/") for f in changed
        )
        if skill_or_agent_changed:
            print()
            print(f"{YELLOW}{BOLD}Restart your Claude Code session{RESET} after this update "
                  f"to pick up changes in skills/agents. Knowledge files load automatically.")

    # Refresh the consuming project if one was given.
    if args.project is not None:
        project = Path(args.project).resolve()
        if not project.is_dir():
            print(f"{RED}[FAIL]{RESET}  not a directory: {project}")
            return 1
        print()
        print(f"{BOLD}Refreshing project: {project}{RESET}")
        install_script = REPO_ROOT / "setup" / "install.py"
        rc = subprocess.run(
            [sys.executable, str(install_script), str(project)],
            check=False,
        ).returncode
        if rc != 0:
            return rc
    else:
        # No project given — point the user at the next step.
        if head_before != head_after:
            print()
            print(f"{DIM}        To refresh a project (CLAUDE.md, .gitignore, symlinks), run:{RESET}")
            print(f"{DIM}        python {REPO_ROOT}/setup/install.py <project-path>{RESET}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
