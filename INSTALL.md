# Installation

Most users should just follow the [Quick Setup in the README](README.md#5-minute-setup) and stop reading. This file covers the long form: what each step does, what the alternatives are, and how to recover when something looks wrong.

## Prerequisites

- **Python 3.9+** (everything in `setup/` and `tools/` is plain stdlib Python).
- **git** (for cloning and for git-tracked operations the kit does inside your project).
- **Claude Code** installed (any recent version).

Optional, only if you'll run Talend builds locally:
- Maven 3.9+
- JDK 17 (the bundled Zulu inside your Talend Studio install is fine)
- A Talend Studio install
- A Talend Management Console Personal Access Token

## Step 1 — clone the kit

Pick any path *outside* any individual Talend project. The kit is shared across projects.

```bash
# macOS / Linux
git clone https://github.com/mkcimt/cimt-claude-talend.git ~/dev/cimt-claude-talend

# Windows
git clone https://github.com/mkcimt/cimt-claude-talend.git C:\dev\cimt-claude-talend
```

## Step 2 — bootstrap into a project

```bash
# macOS / Linux
~/dev/cimt-claude-talend/setup/bootstrap.sh /absolute/path/to/your/talend-project

# Windows
C:\dev\cimt-claude-talend\setup\bootstrap.ps1 C:\path\to\your\talend-project
```

What the bootstrap does, in order:

1. Looks for the companion `claude-qlik-docs` repo. If not found in any common location and not pointed at by `$CLAUDE_QLIK_DOCS`, it clones it next to this one. Without claude-qlik-docs, Claude is still useful but won't know the official Qlik docs.
2. Runs `setup/install.py` with your project path. This step:
   - Writes `export CIMT_TALEND_PATTERNS=...` into your shell rc (`~/.zshrc` on macOS, `~/.bashrc` on Linux, `~/Documents/PowerShell/Microsoft.PowerShell_profile.ps1` on Windows). Single global value — re-running for other projects updates the line in place.
   - Creates **directory junctions** at `<project>/.claude/commands/` → kit's `skills/`, and `<project>/.claude/agents/` → kit's `agents/`. On Windows these are NTFS junctions (no admin rights needed). On macOS/Linux they are regular directory symlinks.
   - Drops `CLAUDE.md`, `.claude/talend.properties`, and `.claude/talend.local.properties` from templates if they don't already exist in the project.
   - Adds `.claude/commands/`, `.claude/agents/`, `.claude/settings.local.json`, and `.claude/talend.local.properties` to the project's `.gitignore` (creates the file if absent).
   - Untracks any legacy `.claude/commands/` or `.claude/agents/` files from the git index — typical for projects that adopted this kit after maintaining those files manually.

## Step 3 — verify

```bash
~/dev/cimt-claude-talend/setup/doctor.py /absolute/path/to/your/talend-project
```

Doctor checks environment, knowledge files, Python tools, project layout, config files, and CLAUDE.md. Each line is one of `[OK]`, `[WARN]`, `[FAIL]` with a fix hint when relevant. Final line is a summary banner.

## Step 4 — open Claude Code

In your Talend project. Claude reads `CLAUDE.md`, picks up the integration block, and is ready. Try a prompt like *"explain what job iXYZ does"* to confirm everything works.

## Running on multiple Talend projects

The installer is **fully idempotent**. Run the bootstrap (or install directly) once per project — re-running on the same project, or running on a second project, is safe and does not duplicate anything:

- The `CIMT_TALEND_PATTERNS` line in your shell rc is updated in place (single global).
- Junctions are recreated cleanly per project.
- `CLAUDE.md`, `talend.properties`, `talend.local.properties` are only created when missing — never overwritten.

Typical consultant setup with three Talend customer projects:

```bash
~/dev/cimt-claude-talend/setup/bootstrap.sh /work/customerA/talend-repo
~/dev/cimt-claude-talend/setup/install.py /work/customerB/talend-repo
~/dev/cimt-claude-talend/setup/install.py /work/customerC/talend-repo
```

(After the first project, you can use `install.py` directly — `claude-qlik-docs` is already cloned.)

## What gets created where

| File / dir | Created on | In git? |
|---|---|---|
| `CLAUDE.md` (in project root) | first install only | yes |
| `.claude/commands` | every install (link) | no (.gitignored) |
| `.claude/agents` | every install (link) | no (.gitignored) |
| `.claude/talend.properties` | first install only | **yes** |
| `.claude/talend.local.properties` | first install only | no (.gitignored) |
| `.gitignore` (or appended to existing) | every install | yes |

## Uninstalling

```bash
~/dev/cimt-claude-talend/setup/install.py --uninstall /path/to/your/project
```

Removes the directory junctions from `<project>/.claude/`. Does **not** delete `CLAUDE.md`, `talend.properties`, or `talend.local.properties` — those are your project's files. The shell-rc line stays — remove it by hand if no projects use the kit any more.

## Recovering from common issues

**`CIMT_TALEND_PATTERNS` not set in your shell.** Run `source ~/.zshrc` (or your shell's rc), or open a new terminal. The installer appended the export but your current shell only loads the rc once at startup.

**Doctor says symlinks/junctions are broken.** The kit's checkout was probably moved or deleted. Re-run `setup/install.py <project>` — it recreates the links pointing at the kit's current location.

**Doctor says `claude-qlik-docs` not found.** Either clone it (`git clone https://github.com/mkcimt/claude-qlik-docs.git ~/dev/claude-qlik-docs`) or, if it's already cloned somewhere unusual, set `CLAUDE_QLIK_DOCS=/path/to/your/checkout` in your shell rc and re-run doctor.

**A `talend.local.properties` value is wrong** (e.g. you moved your Talend Studio install). Either edit the file (it's a simple `.properties` text file), or just tell Claude — it can update the file via `tools/cli.py set`.

**A `talend.properties` value is wrong** (e.g. TMC workspace name changed). Same — edit by hand, or ask Claude.

**TMC PAT expired.** Run `~/dev/cimt-claude-talend/setup/store_pat.py /path/to/your/project` and paste the new token (input is hidden). Or ask Claude to do it.

**Old `talend.config.json` (legacy JSON format) is still in your project.** Re-run `setup/install.py <project>` — it deletes the old file (the new `.properties` files supersede it).
