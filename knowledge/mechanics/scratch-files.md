# Scratch files — where Claude's working files go

## Rule

All temporary files Claude generates during a session — exploratory scripts, JSON dumps, intermediate reports, debug outputs, one-off helpers — go into `.claude/tmp/` in the project root. Create the directory if it doesn't exist.

The `setup/install.py` patches the project's `.gitignore` to exclude `.claude/tmp/`, so the folder is invisible to git and to Talend Studio's Git Staging view.

## Why

Talend Studio's Git Staging panel surfaces every untracked file in the workspace, including Claude's scratch output. Without a dedicated, gitignored scratch directory, three things happen:

1. **Studio shows noise.** The user sees `tmp_compare_tasks.py`, `tmp_report.txt`, `tmp_tasks.json` etc. in the Git Staging view and has to decide each time whether to commit, ignore, or delete.
2. **Files leak into the repo.** A `git add .` or a careless commit pulls scratch files in. Once committed, removing them is a separate cleanup PR.
3. **Cross-session clutter.** Scratch files survive the session that created them. The next session inherits `tmp_recent_compare.py` from a week ago and may either re-use it (with stale assumptions) or duplicate it.

A single gitignored directory solves all three: invisible to git/Studio, easy to wipe between sessions, clearly demarcated as "Claude's working area, not project content."

## What goes in `.claude/tmp/`

- Python/Bash scripts written ad-hoc to query the TMC API, compare run histories, parse logs, etc.
- JSON or text dumps from those scripts (task lists, deployment summaries, audit exports).
- Intermediate diffs or reports the user asked for but doesn't want committed.
- One-shot Maven invocations' captured output, when used for analysis.

## What does NOT go in `.claude/tmp/`

- **Project documentation** (`docs/...`) — that's project content, commit it.
- **Reusable kit tools** — those belong in the cimt-claude-talend repo under `tools/` (Layer 2a).
- **Developer-specific paths or PATs** — those go in `.claude/talend.local.properties`.
- **Session memory** — Claude's auto-memory lives under `~/.claude/projects/.../memory/`.

## Cleanup

Treat `.claude/tmp/` as ephemeral. At the end of a session — or at the start of an unrelated one — feel free to wipe it. Nothing in it should be load-bearing.

If a scratch script turns out to be reusable, **promote it**: move it to `$KIT/tools/` (universal Talend tool) or `scripts/` in the project (project-specific helper), with a real name and a docstring. Don't leave reusable code behind in `tmp/`.

## For existing projects

A project that adopted this kit before this convention existed will have scratch files scattered in `.claude/` directly (or worse, in the project root). On the next `install.py` run:

1. The `.claude/tmp/` entry is added to `.gitignore`.
2. Claude should then move any existing scratch files (typically `.claude/tmp_*` or root-level `tmp_*`) into `.claude/tmp/` and delete the originals.

This is a one-time migration. After that, the convention enforces itself.
