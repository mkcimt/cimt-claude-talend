#!/usr/bin/env python3
"""
update.py — pull the latest cimt-claude-talend, report what changed.

What it does:
  1. `git pull` in the kit's repo.
  2. Detect whether any SKILL.md or agent .md file changed. If yes, the user
     needs to restart their Claude Code session for the new versions to take
     effect (knowledge files reload automatically, skills don't).

Usage:
    update.py
"""

from __future__ import annotations

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
        return 0

    # Summarise what changed.
    diff = git(["diff", "--name-only", head_before, head_after]).stdout.strip()
    changed = [line for line in diff.splitlines() if line]
    print(f"{GREEN}[OK]{RESET}    Pulled {len(changed)} file change(s).")

    skill_or_agent_changed = any(
        f.startswith("skills/") or f.startswith("agents/") for f in changed
    )
    if skill_or_agent_changed:
        print()
        print(f"{YELLOW}{BOLD}Restart your Claude Code session{RESET} to pick up changes "
              f"in skills/agents. Knowledge files load automatically.")
    else:
        print(f"{DIM}        Knowledge files only — no Claude restart needed.{RESET}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
