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


def set_env_var() -> None:
    """Set CIMT_TALEND_PATTERNS persistently for new shells.

    - Windows: `setx` writes to HKCU\\Environment — visible from any new
      cmd, PowerShell, or Git Bash shell. (Does NOT update the current
      process — that's a fundamental setx limitation.)
    - macOS/Linux: append to the shell rc — bash and zsh both read it
      from the right file (.bashrc / .zshrc) at next shell start.
    """
    if is_windows():
        try:
            subprocess.run(
                ["setx", ENV_VAR, str(REPO_ROOT)],
                check=True,
                capture_output=True,
                text=True,
            )
            ok(f"{ENV_VAR} set via setx (visible in new shells)")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            warn(f"could not set {ENV_VAR} via setx: {e}")
            warn("the kit will still work because of the marker file in .claude/, "
                 "but tools invoked from outside the project won't find it")
        return

    # macOS/Linux: shell rc.
    rc_path = shell_rc_path()
    if rc_path is None:
        warn("could not detect shell rc — set $CIMT_TALEND_PATTERNS manually if needed")
        return

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
    ok(f"{ENV_VAR} set in {rc_path}")


def write_kit_path_marker(claude_dir: Path) -> None:
    """Write `.claude/cimt-claude-talend.path` containing the kit's absolute path.

    This is the **primary** mechanism by which Claude finds the kit from a
    project's CLAUDE.md. Robust against shell-rc-not-loaded situations on
    Windows (cmd vs. PowerShell vs. Git Bash mess) — it's just a file in
    the project itself, no env-var indirection.
    """
    claude_dir.mkdir(parents=True, exist_ok=True)
    marker = claude_dir / "cimt-claude-talend.path"
    marker.write_text(str(REPO_ROOT) + "\n", encoding="utf-8")
    ok(f".claude/cimt-claude-talend.path → {REPO_ROOT}")


def _try_remove_link(link: Path) -> bool:
    """Try to remove `link` if it's a symlink, junction, or empty directory.

    Returns True if removed; False if the path doesn't exist or is a regular
    directory with content (which the caller must handle).

    Why this is fiddly: Path.is_symlink() detects POSIX symlinks reliably,
    but Windows junctions confuse Python's `is_symlink()` on some versions.
    Rather than try to *detect* the link type, we just *attempt removal* with
    a sequence of strategies. Whichever succeeds, succeeds.
    """
    if not link.exists() and not link.is_symlink():
        return False
    # Strategy 1: unlink() — works for regular files, POSIX symlinks, and
    # Windows file symlinks. May work for junctions in newer Python on Windows.
    try:
        link.unlink()
        return True
    except (IsADirectoryError, PermissionError, OSError):
        pass
    # Strategy 2: rmdir() — works for empty directories AND Windows junctions
    # (junctions are reparse-point directories; RemoveDirectoryW removes the
    # reparse point without touching the target).
    try:
        link.rmdir()
        return True
    except OSError:
        pass
    return False


def make_directory_link(target: Path, link: Path) -> None:
    """Create a directory symlink/junction at `link` pointing to `target`.

    Existing state handled:
      - link is already a symlink/junction → removed and recreated.
      - link is an empty directory → removed and replaced.
      - link is a directory whose names match the kit's (legacy file-based
        install) → removed and replaced.
      - link is a directory with unknown contents → moved aside to
        `<link>.bak.<timestamp>` so nothing is silently destroyed.
    """
    import time

    removed = _try_remove_link(link)

    if not removed and link.exists() and link.is_dir():
        contents = list(link.iterdir())
        kit_known = {p.name for p in target.iterdir() if p.is_file()}
        if not contents:
            link.rmdir()
        elif all(c.name in kit_known for c in contents):
            shutil.rmtree(link)
        else:
            backup = link.with_name(f"{link.name}.bak.{int(time.time())}")
            link.rename(backup)
            warn(f"existing {link.name}/ moved to {backup.name}/ (had non-kit files)")

    link.parent.mkdir(parents=True, exist_ok=True)

    # Cross-platform creation:
    #   Windows: directory junction via `mklink /J` — works without admin/dev-mode.
    #   POSIX:   regular directory symlink.
    if is_windows():
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        os.symlink(target, link, target_is_directory=True)


def copy_template_if_missing(template_name: str, target: Path) -> bool:
    """Copy a file from templates/ if `target` doesn't exist. Returns True if copied."""
    if target.exists():
        return False
    template = TEMPLATE_DIR / template_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)
    return True


# Integration-block markers in CLAUDE.md.template — used to locate the kit-managed
# region for in-place refresh on re-install.
_BLOCK_COMMENT_PREFIX = "<!-- The block below is for Claude Code"
_BLOCK_START_PREFIX = "> **cimt-claude-talend integration block — START."
_BLOCK_END_PREFIX = "> **cimt-claude-talend integration block — END."


def _find_integration_block(lines: list[str]) -> tuple[int, int] | None:
    """Return (start_idx, end_idx) of the integration block in `lines`, or None.

    Start index: the friendly HTML comment if present, else the `---` divider
    before the START marker if present, else the START marker line.

    End index: the closing `---` divider after the END marker if present, else
    the END marker line.
    """
    start_idx = None
    for i, line in enumerate(lines):
        if line.startswith(_BLOCK_COMMENT_PREFIX):
            start_idx = i
            break
        if line.startswith(_BLOCK_START_PREFIX):
            # No HTML comment in this file — back up one line if a --- divider precedes.
            if i > 0 and lines[i - 1].strip() == "---":
                start_idx = i - 1
            else:
                start_idx = i
            break
    if start_idx is None:
        return None

    end_idx = None
    marker_seen = False
    for i in range(start_idx, len(lines)):
        if lines[i].startswith(_BLOCK_END_PREFIX):
            marker_seen = True
            # Look ahead for a `---` divider, allowing blank lines in between.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip() == "---":
                end_idx = j
            else:
                end_idx = i
            break
    return (start_idx, end_idx) if marker_seen else None


def _backup_claude_md(claude_md: Path) -> Path:
    """Copy CLAUDE.md to CLAUDE.md.bak.<timestamp>; prune older backups (keep latest 3)."""
    import time

    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = claude_md.with_suffix(f".md.bak.{ts}")
    shutil.copy2(claude_md, backup)
    # Keep the 3 most recent backups.
    backups = sorted(
        claude_md.parent.glob(f"{claude_md.name}.bak.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[3:]:
        try:
            old.unlink()
        except OSError:
            pass
    return backup


def refresh_claude_md_block(project_dir: Path) -> str:
    """Replace the kit-managed integration block in the project's CLAUDE.md.

    Returns one of:
      - "created"  — CLAUDE.md didn't exist; copied from template.
      - "refreshed"— CLAUDE.md existed and the block was replaced.
      - "unchanged"— CLAUDE.md existed and its block already matches the template.
      - "skipped"  — CLAUDE.md existed but had no integration markers (manual
                     hand-roll). Left untouched; caller should hint to the user.
    """
    claude_md = project_dir / "CLAUDE.md"
    template_path = TEMPLATE_DIR / "CLAUDE.md.template"

    if not claude_md.exists():
        shutil.copy2(template_path, claude_md)
        return "created"

    template_lines = template_path.read_text(encoding="utf-8").splitlines()
    template_block = _find_integration_block(template_lines)
    if template_block is None:
        # Shouldn't happen — template is the canonical source.
        return "skipped"
    t_start, t_end = template_block
    block_text = "\n".join(template_lines[t_start:t_end + 1])

    existing_lines = claude_md.read_text(encoding="utf-8").splitlines()
    existing_block = _find_integration_block(existing_lines)
    if existing_block is None:
        return "skipped"
    e_start, e_end = existing_block

    existing_block_text = "\n".join(existing_lines[e_start:e_end + 1])
    if existing_block_text == block_text:
        return "unchanged"

    _backup_claude_md(claude_md)

    new_lines = existing_lines[:e_start] + block_text.splitlines() + existing_lines[e_end + 1:]
    claude_md.write_text("\n".join(new_lines) + ("\n" if claude_md.read_text(encoding="utf-8").endswith("\n") else ""), encoding="utf-8")
    return "refreshed"


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
        ".claude/cimt-claude-talend.path",
        # Match any 'worktrees' folder anywhere in the tree — Claude or the user
        # may drop git worktrees inside the project (commonly under .claude/) and
        # those must never be committed.
        "worktrees/",
        ".worktrees/",
        # CLAUDE.md backups created by refresh_claude_md_block() — local recovery
        # files, last 3 kept on disk, never for git.
        "CLAUDE.md.bak.*",
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


def looks_like_talend_project(path: Path) -> bool:
    """A Talend project root contains a subfolder with a `talend.project` file."""
    if not path.is_dir():
        return False
    for sub in path.iterdir():
        if sub.is_dir() and (sub / "talend.project").is_file():
            return True
    return False


def suggest_correct_project_path(given: Path) -> str | None:
    """If `given` is the wrong level, find a plausible correct path and return it.

    Common mistakes:
      - one level too deep: `given` itself contains `talend.project`. Suggest parent.
      - one level too high (Studio workspace): subfolders are Talend project roots.
        Suggest the first/all of them.
    """
    if not given.is_dir():
        return None
    # Too deep: user gave the inner Talend project folder.
    if (given / "talend.project").is_file():
        return f"the parent: {given.parent}"
    # Too high: maybe a Studio workspace. Look for grandchildren with talend.project.
    candidates = []
    for sub in given.iterdir():
        if sub.is_dir() and looks_like_talend_project(sub):
            candidates.append(str(sub))
    if candidates:
        if len(candidates) == 1:
            return f"the project subfolder: {candidates[0]}"
        return "one of these project subfolders:\n        " + "\n        ".join(candidates)
    return None


def install(project_dir: Path) -> int:
    print(f"cimt-claude-talend → installing into {project_dir}")
    print(f"{DIM}        kit at {REPO_ROOT}{RESET}")
    print()

    if not project_dir.is_dir():
        fail(f"not a directory: {project_dir}")
        return 1
    project_dir = project_dir.resolve()

    # Pre-flight: confirm this looks like a Talend project root.
    if not looks_like_talend_project(project_dir):
        fail(f"this does not look like a Talend project root: {project_dir}")
        info("a Talend project root contains a subfolder with a `talend.project` file inside")
        info("(typically a git repository root, not the Studio workspace folder)")
        suggestion = suggest_correct_project_path(project_dir)
        if suggestion:
            print(f"{YELLOW}        Did you mean {suggestion}?{RESET}")
        print()
        info("re-run install.py with the correct path. No changes were made.")
        return 1

    claude_dir = project_dir / ".claude"

    # 1. Marker file in the project — primary mechanism for Claude to find the kit.
    write_kit_path_marker(claude_dir)

    # 2. Shell env var — secondary, for terminal use outside the project.
    set_env_var()

    # 3. Directory junctions for skills + agents.
    try:
        make_directory_link(REPO_ROOT / "skills", claude_dir / "commands")
        ok(".claude/commands → kit's skills/")
        make_directory_link(REPO_ROOT / "agents", claude_dir / "agents")
        ok(".claude/agents → kit's agents/")
    except Exception as e:
        fail(f"could not create directory link: {e}")
        return 1

    # 3. CLAUDE.md — create from template if missing, refresh integration block if present.
    status = refresh_claude_md_block(project_dir)
    if status == "created":
        ok("CLAUDE.md created from template")
    elif status == "refreshed":
        ok("CLAUDE.md integration block refreshed (previous version backed up to CLAUDE.md.bak.*)")
    elif status == "unchanged":
        ok("CLAUDE.md integration block already up to date")
    elif status == "skipped":
        warn("CLAUDE.md exists but has no integration-block markers — merge the block manually")
        info(f"see {TEMPLATE_DIR / 'CLAUDE.md.template'}")

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
