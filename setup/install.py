#!/usr/bin/env python3
"""
install.py — set up cimt-claude-talend in a Talend project.

Cross-platform: macOS, Linux, Windows. Idempotent. Safe to re-run.

Usage:
    install.py <absolute-path-to-talend-project>
    install.py --uninstall <absolute-path-to-talend-project>

What it does (on install):
  1. Sets CIMT_TALEND_PATTERNS in your shell rc (or PowerShell profile).
  2. Junctions the kit's skills/ and agents/ directories into the project's
     .claude/commands/ and .claude/agents/ (Windows uses directory junctions —
     no admin rights needed).
  3. Copies CLAUDE.md from the template if the project doesn't have one.
  4. Copies talend.properties and talend.local.properties from templates if
     they don't exist.
  5. Adds the necessary entries to the project's .gitignore.
  6. Untracks any legacy .claude/commands/ or .claude/agents/ files in the
     git index (typical for projects that adopted this kit after the fact).

Output is minimal and unambiguous: green OK lines for what was done, red FAIL
lines for what wasn't. No next-step litany — Claude takes over from here.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "templates"
ENV_VAR = "CIMT_TALEND_PATTERNS"

# ANSI colour codes (Windows 10+ supports them in modern terminals).
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET}    {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"{RED}[FAIL]{RESET}  {msg}")


def info(msg: str) -> None:
    print(f"{DIM}        {msg}{RESET}")


def is_windows() -> bool:
    return sys.platform == "win32"


def shell_rc_path() -> Path | None:
    """Return the user's shell rc / PowerShell profile path, or None if unknown."""
    if is_windows():
        # PowerShell user profile. WindowsPowerShell == legacy, PowerShell == PS Core 7+.
        # We pick PowerShell 7+ profile if PowerShell is available, else fall back.
        userprofile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        return userprofile / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    if shell.endswith("/zsh"):
        return home / ".zshrc"
    if shell.endswith("/bash"):
        return home / ".bashrc"
    return home / ".profile"


def set_env_var(rc_path: Path) -> None:
    """Add or update the CIMT_TALEND_PATTERNS line in the shell rc."""
    if is_windows():
        line = f'$env:{ENV_VAR} = "{REPO_ROOT}"'
        marker_prefix = f"$env:{ENV_VAR}"
    else:
        line = f'export {ENV_VAR}="{REPO_ROOT}"'
        marker_prefix = f"export {ENV_VAR}="

    rc_path.parent.mkdir(parents=True, exist_ok=True)
    if rc_path.exists():
        lines = rc_path.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, existing in enumerate(lines):
            if existing.strip().startswith(marker_prefix):
                lines[i] = line
                updated = True
                break
        if not updated:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(line)
        rc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        rc_path.write_text(line + "\n", encoding="utf-8")

    ok(f"{ENV_VAR} pointed at this repo in {rc_path}")


def make_directory_link(target: Path, link: Path) -> None:
    """Create a directory symlink/junction at `link` pointing to `target`.

    Replaces an existing link if present. If a regular directory exists at
    the link path: empty → delete; kit-known content (file names match the
    kit's) → delete (legacy file-based install); anything else → move aside
    to `<link>.bak.<timestamp>` so nothing is silently destroyed.
    """
    import time

    if link.is_symlink() or (is_windows() and _is_windows_junction(link)):
        link.unlink()
    elif link.exists():
        if link.is_dir():
            contents = list(link.iterdir())
            kit_known = {p.name for p in target.iterdir() if p.is_file()}
            if not contents:
                shutil.rmtree(link)
            elif all(c.name in kit_known for c in contents):
                # Legacy file-based install — same names as kit, safe to drop.
                shutil.rmtree(link)
            else:
                # Unknown content — preserve it.
                backup = link.with_name(f"{link.name}.bak.{int(time.time())}")
                link.rename(backup)
                warn(f"existing {link.name}/ moved to {backup.name}/ (had non-kit files)")
        else:
            link.unlink()

    link.parent.mkdir(parents=True, exist_ok=True)

    # os.symlink with a directory target on Windows uses a directory symlink (needs
    # developer mode) or junction (doesn't). For maximum compatibility we use
    # mklink /J on Windows explicitly.
    if is_windows():
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        os.symlink(target, link, target_is_directory=True)


def _is_windows_junction(path: Path) -> bool:
    """Detect a Windows junction (reparse point pointing at a directory)."""
    if not is_windows() or not path.exists():
        return False
    try:
        return bool(path.stat().st_reparse_tag)  # type: ignore[attr-defined]
    except AttributeError:
        # Fallback for older Python on Windows.
        return os.path.isdir(path) and os.readlink(str(path)) != str(path)


def copy_template_if_missing(template_name: str, target: Path) -> bool:
    """Copy a file from templates/ if `target` doesn't exist. Returns True if copied."""
    if target.exists():
        return False
    template = TEMPLATE_DIR / template_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)
    return True


def update_gitignore(project_dir: Path) -> int:
    """Add the required entries to .gitignore. Returns count of new entries.

    Critically: .claude/commands and .claude/agents are *symlinks/junctions*,
    not regular directories. .gitignore entries for them must NOT have a
    trailing slash — a trailing slash means "directory only" and won't match
    a symlink-to-a-directory. Without this, git would silently track the
    symlink (mode 120000) with the developer's absolute path baked in.
    """
    gitignore = project_dir / ".gitignore"
    header_lines = [
        "# cimt-claude-talend — developer-specific Claude Code state (do not commit).",
        "# No trailing slashes — .claude/commands and .claude/agents are symlinks /",
        "# junctions to the kit, not regular directories, and trailing slashes would",
        "# fail to match them.",
    ]
    entries = [
        ".claude/commands",
        ".claude/agents",
        ".claude/settings.local.json",
        ".claude/talend.local.properties",
    ]

    if not gitignore.exists():
        body = "\n".join(header_lines + entries) + "\n"
        gitignore.write_text(body, encoding="utf-8")
        return len(entries)

    existing = gitignore.read_text(encoding="utf-8")
    # Match each entry whether the existing line has a trailing slash or not.
    existing_lines = {line.strip().rstrip("/").lstrip("/")
                      for line in existing.splitlines() if line.strip()}
    added = []
    for entry in entries:
        if entry.rstrip("/") not in existing_lines:
            added.append(entry)

    # Also: detect and warn about existing trailing-slash entries for the symlinks.
    needs_slash_fix = []
    for raw in existing.splitlines():
        s = raw.strip()
        if s in (".claude/commands/", ".claude/agents/"):
            needs_slash_fix.append(s)

    if not added and not needs_slash_fix:
        return 0

    new_text = existing
    if needs_slash_fix:
        # Strip the trailing slash on existing entries in place.
        for bad in needs_slash_fix:
            new_text = new_text.replace(bad + "\n", bad.rstrip("/") + "\n")
            new_text = new_text.replace("\n" + bad, "\n" + bad.rstrip("/"))

    if added:
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += "\n" + "\n".join(header_lines) + "\n" + "\n".join(added) + "\n"

    gitignore.write_text(new_text, encoding="utf-8")
    return len(added) + len(needs_slash_fix)


def is_git_repo(path: Path) -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def untrack_legacy_claude_files(project_dir: Path) -> int:
    """Run `git rm --cached` on any tracked .claude/commands/ or .claude/agents/ files."""
    if not is_git_repo(project_dir):
        return 0
    result = subprocess.run(
        ["git", "-C", str(project_dir), "ls-files", ".claude/commands/", ".claude/agents/"],
        check=True,
        capture_output=True,
        text=True,
    )
    files = [line for line in result.stdout.splitlines() if line.strip()]
    if not files:
        return 0
    subprocess.run(
        ["git", "-C", str(project_dir), "rm", "--cached", "-q", *files],
        check=True,
    )
    return len(files)


def cleanup_legacy_json_config(project_dir: Path) -> bool:
    """Remove the old talend.config.json if present. Returns True if removed."""
    old = project_dir / ".claude" / "talend.config.json"
    if old.exists():
        old.unlink()
        if is_git_repo(project_dir):
            # Untrack it too if it was committed.
            subprocess.run(
                ["git", "-C", str(project_dir), "rm", "-q", "--cached", "--ignore-unmatch",
                 ".claude/talend.config.json"],
                check=False,
            )
        return True
    return False


def install(project_dir: Path) -> int:
    print(f"cimt-claude-talend → installing into {project_dir}")
    print(f"{DIM}        kit at {REPO_ROOT}{RESET}")
    print()

    if not project_dir.is_dir():
        fail(f"not a directory: {project_dir}")
        return 1
    project_dir = project_dir.resolve()
    claude_dir = project_dir / ".claude"

    # 1. Shell env var.
    rc = shell_rc_path()
    if rc is None:
        warn("could not detect shell rc location — set CIMT_TALEND_PATTERNS manually")
    else:
        set_env_var(rc)

    # 2. Directory junctions for skills + agents.
    try:
        make_directory_link(REPO_ROOT / "skills", claude_dir / "commands")
        ok(".claude/commands → kit's skills/")
        make_directory_link(REPO_ROOT / "agents", claude_dir / "agents")
        ok(".claude/agents → kit's agents/")
    except Exception as e:
        fail(f"could not create directory link: {e}")
        return 1

    # 3. CLAUDE.md template.
    if copy_template_if_missing("CLAUDE.md.template", project_dir / "CLAUDE.md"):
        ok("CLAUDE.md created from template")
    else:
        ok("CLAUDE.md already exists (left untouched)")

    # 4. talend.properties + talend.local.properties.
    if copy_template_if_missing("talend.properties.example", claude_dir / "talend.properties"):
        ok(".claude/talend.properties created from template")
    else:
        ok(".claude/talend.properties already exists (left untouched)")

    if copy_template_if_missing("talend.local.properties.example",
                                claude_dir / "talend.local.properties"):
        ok(".claude/talend.local.properties created from template")
    else:
        ok(".claude/talend.local.properties already exists (left untouched)")

    # 5. Remove legacy talend.config.json if it exists.
    if cleanup_legacy_json_config(project_dir):
        ok(".claude/talend.config.json removed (superseded by .properties files)")

    # 6. .gitignore.
    added = update_gitignore(project_dir)
    if added:
        ok(f".gitignore updated ({added} new entry/entries)")
    else:
        ok(".gitignore already covers cimt-claude-talend entries")

    # 7. Untrack legacy tracked .claude files.
    untracked = untrack_legacy_claude_files(project_dir)
    if untracked:
        ok(f"{untracked} legacy file(s) untracked from git — commit the change on a feature branch")

    print()
    print(f"{GREEN}Setup OK.{RESET} Open Claude Code in the project. It will guide you through anything else.")
    return 0


def uninstall(project_dir: Path) -> int:
    print(f"cimt-claude-talend → uninstalling from {project_dir}")
    print()

    project_dir = project_dir.resolve()
    claude_dir = project_dir / ".claude"

    for name in ("commands", "agents"):
        link = claude_dir / name
        if link.is_symlink() or _is_windows_junction(link):
            link.unlink()
            ok(f".claude/{name} link removed")
        else:
            ok(f".claude/{name} was not a kit link (left as-is)")

    print()
    print(f"{GREEN}Uninstall OK.{RESET}")
    print(f"{DIM}        CLAUDE.md, talend.properties, talend.local.properties left alone — they belong to your project.{RESET}")
    print(f"{DIM}        Remove the {ENV_VAR} line from your shell rc manually if no projects use it.{RESET}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="install.py", description=__doc__)
    p.add_argument("--uninstall", action="store_true", help="remove the kit's links from the project")
    p.add_argument("project", help="absolute path to your Talend project")
    args = p.parse_args(argv)

    project = Path(args.project)
    if args.uninstall:
        return uninstall(project)
    return install(project)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
