#!/usr/bin/env python3
"""
update.py — pull the latest cimt-claude-talend; optionally refresh a project.

Both modes also pull the companion `claude-qlik-docs` repo (the Qlik
official-docs skill) so newly pushed doc sections land locally. The docs repo
lives outside this kit — bootstrap.py clones it once; without this step a kit
update would leave the docs stale.

Two modes:

  update.py
    Pulls the kit's repo and the companion claude-qlik-docs repo. Reports what
    changed. Reminds you to re-run install.py on consuming projects if templates
    changed.

  update.py <project-path>
    Pulls (kit + docs), then immediately re-runs install.py on that project so
    its CLAUDE.md integration block, .gitignore, and symlinks are refreshed to
    match the new kit version. This is what Claude calls when the user
    says "update cimt-claude-talend" — `<project-path>` is the project the
    user is currently working in.

If skill or agent files changed, the user needs to restart their Claude Code
session for those to take effect (knowledge files — including the Qlik docs —
reload automatically).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QLIK_REPO_URL = "https://github.com/mkcimt/claude-qlik-docs.git"

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


def find_qlik_docs() -> Path | None:
    """Locate the companion claude-qlik-docs checkout.

    Mirrors the search in bootstrap.py / doctor.py so all three agree on where
    the docs live: the CLAUDE_QLIK_DOCS env var first, then common dev folders.
    """
    env = os.environ.get("CLAUDE_QLIK_DOCS")
    if env and Path(env).exists():
        return Path(env)
    home = Path.home()
    candidates = [
        REPO_ROOT.parent / "claude-qlik-docs",
        home / "dev" / "claude-qlik-docs",
        home / "Entwicklung" / "claude-qlik-docs",
        home / "projects" / "claude-qlik-docs",
        home / "code" / "claude-qlik-docs",
        home / "repos" / "claude-qlik-docs",
        home / "Documents" / "claude-qlik-docs",
    ]
    if sys.platform == "win32":
        candidates.extend([
            Path(r"C:\dev\claude-qlik-docs"),
            Path(r"C:\var\opt\claude-qlik-docs"),
        ])
    return next((c for c in candidates if c.exists()), None)


def pull_qlik_docs() -> None:
    """Pull the companion claude-qlik-docs repo so the Qlik official-docs skill
    reflects the latest pushed sections.

    Non-fatal by design: a missing checkout or a non-fast-forward state warns
    but never fails the kit update — the kit is still usable without it.
    """
    print()
    print(f"{BOLD}Updating companion: claude-qlik-docs{RESET}")
    docs = find_qlik_docs()
    if docs is None:
        print(f"{YELLOW}[WARN]{RESET}  claude-qlik-docs not found — skipping.")
        print(f"{DIM}        Clone it with: git clone {QLIK_REPO_URL}{RESET}")
        print(f"{DIM}        or set CLAUDE_QLIK_DOCS=/path/to/checkout, then re-run.{RESET}")
        return
    print(f"{DIM}        {docs}{RESET}")

    def dgit(a: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(docs), *a], check=False, capture_output=True, text=True
        )

    before = dgit(["rev-parse", "HEAD"]).stdout.strip()
    result = dgit(["pull", "--ff-only"])
    if result.returncode != 0:
        print(f"{YELLOW}[WARN]{RESET}  git pull failed in claude-qlik-docs (not fatal):")
        print(result.stderr.rstrip())
        return
    after = dgit(["rev-parse", "HEAD"]).stdout.strip()
    if before == after:
        print(f"{GREEN}[OK]{RESET}    Already up to date.")
    else:
        diff = dgit(["diff", "--name-only", before, after]).stdout.strip()
        n = len([line for line in diff.splitlines() if line])
        print(f"{GREEN}[OK]{RESET}    Pulled {n} file change(s). Qlik docs reload automatically.")


def main() -> int:
    # Windows consoles default to cp1252, which can't encode some characters
    # this script (and the install.py it spawns) prints. Force UTF-8 so it
    # doesn't crash mid-output; replace-on-error means a truly hopeless codec
    # still prints something instead of raising.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

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
        # Fall through regardless: the companion docs repo and (if given) the
        # project still get refreshed even when the kit itself is unchanged.

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

    # Pull the companion Qlik docs repo so its skill stays in sync. Always runs,
    # regardless of whether the kit itself had changes.
    pull_qlik_docs()

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
