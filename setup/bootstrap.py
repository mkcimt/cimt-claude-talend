#!/usr/bin/env python3
"""
bootstrap.py — one-command setup for cimt-claude-talend in a Talend project.

What it does:
  1. Ensures the companion `claude-qlik-docs` repo is cloned alongside this one.
  2. Runs setup/install.py on your Talend project.

Usage (from the kit's checkout):
    setup/bootstrap.py <absolute-path-to-talend-project>

If you ran this via the bootstrap.sh / bootstrap.ps1 shim, the shim already
found Python and forwarded the argument here.

Idempotent: re-runnable safely. If qlik-docs is already cloned at a known
location, the clone step is skipped.
"""

from __future__ import annotations

import argparse
import os
import shutil
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


def ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET}    {msg}")


def info(msg: str) -> None:
    print(f"{DIM}        {msg}{RESET}")


def fail(msg: str) -> int:
    print(f"{RED}[FAIL]{RESET}  {msg}")
    return 1


def is_windows() -> bool:
    return sys.platform == "win32"


def find_qlik_docs() -> Path | None:
    """Look in the env var first, then common dev-folder locations."""
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
    if is_windows():
        candidates.extend([
            Path(r"C:\dev\claude-qlik-docs"),
            Path(r"C:\var\opt\claude-qlik-docs"),
        ])
    return next((c for c in candidates if c.exists()), None)


def ensure_qlik_docs() -> Path | None:
    """Find or clone claude-qlik-docs. Returns its path, or None if clone failed."""
    existing = find_qlik_docs()
    if existing:
        ok(f"claude-qlik-docs already at {existing}")
        return existing

    if shutil.which("git") is None:
        fail("git is not installed (or not in PATH) — cannot clone claude-qlik-docs")
        info("install git from https://git-scm.com and re-run bootstrap")
        return None

    # Clone alongside the kit checkout.
    target = REPO_ROOT.parent / "claude-qlik-docs"
    print(f"cloning claude-qlik-docs to {target} ...")
    result = subprocess.run(
        ["git", "clone", QLIK_REPO_URL, str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail("clone failed:")
        print(result.stderr)
        return None
    ok(f"claude-qlik-docs cloned to {target}")
    return target


def run_install(project_dir: Path) -> int:
    install_script = REPO_ROOT / "setup" / "install.py"
    # Invoke the install script with the same Python that's running us.
    print()
    result = subprocess.run(
        [sys.executable, str(install_script), str(project_dir)],
        check=False,
    )
    return result.returncode


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="bootstrap.py", description=__doc__)
    p.add_argument("project", help="absolute path to your Talend project")
    args = p.parse_args(argv)

    project = Path(args.project).resolve()
    if not project.is_dir():
        return fail(f"not a directory: {project}")

    print(f"{BOLD}cimt-claude-talend bootstrap{RESET}")
    print(f"{DIM}        kit at {REPO_ROOT}{RESET}")
    print(f"{DIM}        target project: {project}{RESET}")
    print()

    qlik = ensure_qlik_docs()
    if qlik is None:
        print()
        print(f"{YELLOW}Continuing without claude-qlik-docs.{RESET} You can install it later "
              f"and re-run this script — install.py is idempotent.")
        print()

    return run_install(project)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
