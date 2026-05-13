#!/usr/bin/env python3
"""
cimt-claude-talend config CLI.

Read and write `.claude/talend.properties` and `.claude/talend.local.properties`
without the user having to know the file format or location. Claude calls this
when it needs to set or look up a config value during a session.

Usage:
    cli.py get <project-path> <key> [--default <fallback>]
    cli.py set <project-path> <key> <value>
    cli.py unset <project-path> <key>
    cli.py list <project-path>                     # show all current values

Local config (talend.local.properties) is gitignored and holds developer-
specific values: paths, PAT. Project config (talend.properties) is committed
and holds project-shared values: TMC workspace, env chain, etc.

Keys are routed automatically:
- `talend.studio.path`, `talend.framework.path`, `tmc.pat` → local file
- everything else                                          → project file

The file is created from the template if it doesn't exist yet.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Make `from properties import ...` work whether invoked as `cli.py` or `python -m`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import properties  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "templates"

# Per-developer keys live in talend.local.properties (gitignored).
LOCAL_KEYS = {
    "talend.studio.path",
    "talend.framework.path",
    "tmc.pat",
}


def config_paths(project_dir: Path) -> tuple[Path, Path]:
    """Return (project_config_path, local_config_path) for a project."""
    claude_dir = project_dir / ".claude"
    return (
        claude_dir / "talend.properties",
        claude_dir / "talend.local.properties",
    )


def file_for_key(key: str, project_dir: Path) -> Path:
    """Decide whether a key belongs in the local or shared properties file."""
    project_cfg, local_cfg = config_paths(project_dir)
    return local_cfg if key in LOCAL_KEYS else project_cfg


def ensure_file(path: Path) -> None:
    """Create the file from its template if it doesn't exist yet."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    template = TEMPLATE_DIR / f"{path.name}.example"
    if template.exists():
        shutil.copy2(template, path)
    else:
        path.touch()


def cmd_get(args: argparse.Namespace) -> int:
    target = file_for_key(args.key, Path(args.project).resolve())
    if not target.exists():
        if args.default is not None:
            print(args.default)
            return 0
        return 1
    value = properties.get(target, args.key, default=args.default)
    if value is None:
        return 1
    print(value)
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    target = file_for_key(args.key, project)
    ensure_file(target)
    properties.set_value(target, args.key, args.value)
    return 0


def cmd_unset(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    target = file_for_key(args.key, project)
    properties.unset(target, args.key)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    project_cfg, local_cfg = config_paths(project)
    for label, path in [("# project (committed)", project_cfg), ("# local (gitignored)", local_cfg)]:
        print(label, "→", path)
        if not path.exists():
            print("  (file does not exist)")
            continue
        for key, value in properties.load(path).items():
            display = "***" if key == "tmc.pat" and value else value
            print(f"  {key} = {display}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="cli.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="print a config value")
    g.add_argument("project")
    g.add_argument("key")
    g.add_argument("--default", default=None)
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("set", help="write a config value (creates file from template if missing)")
    s.add_argument("project")
    s.add_argument("key")
    s.add_argument("value")
    s.set_defaults(func=cmd_set)

    u = sub.add_parser("unset", help="remove a config value")
    u.add_argument("project")
    u.add_argument("key")
    u.set_defaults(func=cmd_unset)

    ls = sub.add_parser("list", help="list all config values for a project (masks tmc.pat)")
    ls.add_argument("project")
    ls.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
