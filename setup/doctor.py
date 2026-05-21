#!/usr/bin/env python3
"""
doctor.py — verify cimt-claude-talend is wired up correctly.

Cross-platform. Run by the user when something looks wrong, or by Claude
automatically the first time it needs the toolkit in a session.

Usage:
    doctor.py                  # kit-level only (env var, knowledge files, tools)
    doctor.py <project-path>   # also check the project integration

Exits 0 if everything is OK, 1 if any check failed. WARN-level issues do not
fail the run by themselves but contribute to the final summary.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_VAR = "CIMT_TALEND_PATTERNS"

# Make `from properties import ...` work whether invoked as setup/doctor.py or via shim.
sys.path.insert(0, str(REPO_ROOT / "tools"))
import properties  # noqa: E402

# ANSI colours.
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class Report:
    def __init__(self) -> None:
        self.oks = 0
        self.warns = 0
        self.fails = 0

    def ok(self, msg: str) -> None:
        self.oks += 1
        print(f"  {GREEN}[OK]{RESET}   {msg}")

    def warn(self, msg: str, fix: str | None = None) -> None:
        self.warns += 1
        print(f"  {YELLOW}[WARN]{RESET} {msg}")
        if fix:
            print(f"        {DIM}fix: {fix}{RESET}")

    def fail(self, msg: str, fix: str | None = None) -> None:
        self.fails += 1
        print(f"  {RED}[FAIL]{RESET} {msg}")
        if fix:
            print(f"        {DIM}fix: {fix}{RESET}")

    def banner(self) -> int:
        print()
        if self.fails == 0 and self.warns == 0:
            print(f"{GREEN}{BOLD}All checks passed.{RESET}")
            return 0
        if self.fails == 0:
            print(f"{YELLOW}{BOLD}{self.warns} warning(s).{RESET} Setup will still work — see fix hints above.")
            return 0
        print(f"{RED}{BOLD}{self.fails} failure(s) and {self.warns} warning(s).{RESET} See fix hints above.")
        return 1


def section(title: str) -> None:
    print(f"\n{BOLD}== {title} =={RESET}")


# ---------------------------------------------------------------------------
# Kit-level checks
# ---------------------------------------------------------------------------

EXPECTED_KNOWLEDGE_FILES = [
    "knowledge/INDEX.md",
    "knowledge/mechanics/item-file-format.md",
    "knowledge/mechanics/git-workflow.md",
    "knowledge/mechanics/item-properties-touch.md",
    "knowledge/mechanics/studio-noise-filter.md",
    "knowledge/patterns/context-variables.md",
    "knowledge/tmc/task-management.md",
    "knowledge/tmc/microservice-lifecycle.md",
    "knowledge/tmc/deployment-modes.md",
    "knowledge/tmc/known-bugs.md",
    "knowledge/build-publish/release-runbook.md",
    "knowledge/build-publish/maven-build.md",
    "knowledge/code-review/principles.md",
    "knowledge/documentation/conventions.md",
]


def check_env_var(report: Report) -> None:
    section("Environment")
    value = os.environ.get(ENV_VAR)
    if value:
        set_path = Path(value).resolve()
        if set_path != REPO_ROOT.resolve():
            report.warn(
                f"{ENV_VAR}={value} but this repo is at {REPO_ROOT}",
                "re-run setup/install.py from this repo if you want the env var to match",
            )
        else:
            report.ok(f"{ENV_VAR} points at this repo")
    else:
        # Not set in the current shell. That's OK — projects find the kit via
        # the .claude/cimt-claude-talend.path marker file instead. Note it but
        # do not fail.
        report.warn(
            f"{ENV_VAR} is not set in this shell",
            "harmless if you use Claude inside the project (it uses the marker file in "
            ".claude/), but tools invoked from outside any project will need either the "
            "env var or an absolute path. Open a new terminal to pick up the value set "
            "by install.py.",
        )


def check_knowledge(report: Report) -> None:
    section("Knowledge base")
    missing = []
    for rel in EXPECTED_KNOWLEDGE_FILES:
        if not (REPO_ROOT / rel).exists():
            missing.append(rel)
    if missing:
        for rel in missing:
            report.fail(f"missing: {rel}", "your checkout is incomplete — `git pull` in the kit repo")
    else:
        report.ok(f"all {len(EXPECTED_KNOWLEDGE_FILES)} knowledge files present")


def check_tools(report: Report) -> None:
    section("Python tools")
    expected_tools = ["properties.py", "cli.py", "tmc_release.py",
                      "tmc_microservice_ops.py", "touch_item_properties.py"]
    for name in expected_tools:
        p = REPO_ROOT / "tools" / name
        if not p.exists():
            report.fail(f"missing: tools/{name}", "checkout incomplete")
            continue
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
            report.ok(f"tools/{name} parses cleanly")
        except SyntaxError as e:
            report.fail(f"tools/{name} has a syntax error: {e}", "report this as a bug")


def check_skills_agents(report: Report) -> None:
    section("Skills + agents")
    for sub, label in [("skills", "skill"), ("agents", "agent")]:
        d = REPO_ROOT / sub
        if not d.is_dir():
            report.fail(f"missing directory: {sub}/", "checkout incomplete")
            continue
        files = list(d.glob("*.md"))
        report.ok(f"{len(files)} {label}(s) in {sub}/")


def check_qlik_docs_sibling(report: Report) -> None:
    section("Companion: claude-qlik-docs")
    # 1. Explicit env var.
    env = os.environ.get("CLAUDE_QLIK_DOCS")
    if env and Path(env).exists():
        report.ok(f"claude-qlik-docs at {env} (via CLAUDE_QLIK_DOCS)")
        return
    # 2. Common locations.
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
    found = next((c for c in candidates if c.exists()), None)
    if found:
        report.ok(f"claude-qlik-docs checkout at {found}")
    else:
        report.warn(
            "claude-qlik-docs not found in common locations",
            "this kit works without it, but Claude is more useful when both are installed. "
            "Install with: git clone https://github.com/mkcimt/claude-qlik-docs "
            "(or set CLAUDE_QLIK_DOCS to your existing checkout)",
        )


# ---------------------------------------------------------------------------
# Project-level checks
# ---------------------------------------------------------------------------


def check_project_layout(report: Report, project_dir: Path) -> None:
    section(f"Project: {project_dir}")
    if not project_dir.is_dir():
        report.fail(f"not a directory: {project_dir}")
        return

    claude_dir = project_dir / ".claude"
    if not claude_dir.is_dir():
        report.fail(f"{claude_dir} does not exist", f"run setup/install.py {project_dir}")
        return

    # Marker file — the primary mechanism Claude uses to find the kit.
    marker = claude_dir / "cimt-claude-talend.path"
    if marker.exists():
        path = marker.read_text(encoding="utf-8").strip()
        if Path(path).resolve() == REPO_ROOT.resolve():
            report.ok(f".claude/cimt-claude-talend.path → this repo")
        else:
            report.warn(
                f".claude/cimt-claude-talend.path points at {path}, not this repo ({REPO_ROOT})",
                f"re-run setup/install.py {project_dir} to refresh the marker",
            )
    else:
        report.fail(
            ".claude/cimt-claude-talend.path missing — Claude won't be able to find the kit",
            f"run setup/install.py {project_dir}",
        )

    # Commands + agents links.
    for sub in ("commands", "agents"):
        link = claude_dir / sub
        if link.is_symlink() or _is_windows_junction(link):
            target = Path(os.readlink(link)) if link.is_symlink() else link
            try:
                resolved = link.resolve(strict=True)
                report.ok(f".claude/{sub} → {resolved}")
            except (FileNotFoundError, OSError):
                report.fail(
                    f".claude/{sub} link is broken (target missing: {target})",
                    f"the kit may have moved — re-run setup/install.py {project_dir}",
                )
        elif link.is_dir():
            report.warn(
                f".claude/{sub} is a regular directory, not a kit link",
                f"run setup/install.py {project_dir} to convert it",
            )
        else:
            report.fail(
                f".claude/{sub} is missing",
                f"run setup/install.py {project_dir}",
            )


def check_project_config(report: Report, project_dir: Path) -> None:
    section("Project config files")
    claude_dir = project_dir / ".claude"
    project_cfg = claude_dir / "talend.properties"
    local_cfg = claude_dir / "talend.local.properties"
    legacy = claude_dir / "talend.config.json"

    if legacy.exists():
        report.warn(
            ".claude/talend.config.json still present (superseded by .properties files)",
            f"run setup/install.py {project_dir} again to clean it up",
        )

    if not project_cfg.exists():
        report.fail(
            ".claude/talend.properties missing",
            f"run setup/install.py {project_dir}",
        )
    else:
        report.ok(".claude/talend.properties present")
        check_project_values(report, project_cfg, project_dir)

    if not local_cfg.exists():
        report.fail(
            ".claude/talend.local.properties missing",
            f"run setup/install.py {project_dir}",
        )
    else:
        report.ok(".claude/talend.local.properties present")
        check_local_values(report, local_cfg, project_dir)


def check_project_values(report: Report, cfg: Path, project_dir: Path) -> None:
    cfg_data = properties.load(cfg)
    workspace = cfg_data.get("tmc.workspace", "")
    if not workspace or workspace == "your-tmc-workspace":
        report.warn(
            "talend.properties: tmc.workspace not set yet",
            "Claude will ask the first time it needs to publish or deploy",
        )

    region = cfg_data.get("tmc.region", "")
    if region and region not in {"eu", "us", "us-west", "ap", "au"}:
        report.warn(f"talend.properties: tmc.region={region} is unusual (eu/us/us-west/ap/au)")


def check_local_values(report: Report, cfg: Path, project_dir: Path) -> None:
    cfg_data = properties.load(cfg)
    studio_path = cfg_data.get("talend.studio.path", "")
    if studio_path:
        p = Path(studio_path)
        if not p.exists():
            report.warn(
                f"talend.local.properties: talend.studio.path={studio_path} does not exist",
                "check the path or leave empty; Claude will ask when a build needs it",
            )
        else:
            report.ok(f"talend.studio.path → {p}")

    framework_path = cfg_data.get("talend.framework.path", "")
    if framework_path:
        p = Path(framework_path)
        if not p.exists():
            report.warn(
                f"talend.local.properties: talend.framework.path={framework_path} does not exist",
                "check the path, or leave empty if this project doesn't use an external framework",
            )

    pat = cfg_data.get("tmc.pat", "")
    if pat:
        if len(pat) < 20:
            report.warn(
                "talend.local.properties: tmc.pat looks too short for a real PAT",
                "double-check you pasted the full token",
            )


def check_claude_md(report: Report, project_dir: Path) -> None:
    section("CLAUDE.md")
    p = project_dir / "CLAUDE.md"
    if not p.exists():
        report.fail("CLAUDE.md missing", f"run setup/install.py {project_dir}")
        return
    body = p.read_text(encoding="utf-8")
    if "cimt-claude-talend integration block — START" in body:
        report.ok("CLAUDE.md contains the integration block")
    else:
        report.warn(
            "CLAUDE.md does not contain the cimt-claude-talend integration block",
            "merge the block from templates/CLAUDE.md.template (see the kit's README)",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_windows() -> bool:
    return sys.platform == "win32"


def _is_windows_junction(path: Path) -> bool:
    if not is_windows() or not path.exists():
        return False
    try:
        return bool(os.lstat(path).st_reparse_tag)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def main(argv: list[str]) -> int:
    # Windows consoles default to cp1252; the report contains characters like
    # U+2192 (→) that can't encode there. Force UTF-8 so doctor doesn't crash
    # mid-report. Replace-on-error means a truly hopeless codec still prints
    # something instead of raising.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    p = argparse.ArgumentParser(prog="doctor.py", description=__doc__)
    p.add_argument("project", nargs="?", help="absolute path to your Talend project (optional)")
    args = p.parse_args(argv)

    print(f"{BOLD}cimt-claude-talend doctor{RESET}")
    print(f"{DIM}        kit at {REPO_ROOT}{RESET}")

    report = Report()
    check_env_var(report)
    check_knowledge(report)
    check_tools(report)
    check_skills_agents(report)
    check_qlik_docs_sibling(report)

    if args.project:
        project_dir = Path(args.project).resolve()
        check_project_layout(report, project_dir)
        check_project_config(report, project_dir)
        check_claude_md(report, project_dir)

    return report.banner()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
