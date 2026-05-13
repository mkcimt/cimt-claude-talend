# Installation

## Prerequisites

- Python 3.9+ (for the release tools)
- Maven 3.9+, JDK 17 (only if you'll run build/publish locally)
- A Talend Studio project (Studio 8.x) checked out somewhere
- Optionally: a Talend Personal Access Token (PAT) for TMC API operations

## Step 1 — Clone this repo

Choose a location *outside* your Talend project workspace. Recommended:

```
# macOS / Linux
git clone https://github.com/mkcimt/cimt-claude-talend.git ~/dev/cimt-claude-talend

# Windows (PowerShell)
git clone https://github.com/mkcimt/cimt-claude-talend.git C:\var\opt\cimt-claude-talend
```

The exact path is yours to pick — `install.sh` will record it in your shell rc.

## Step 2 — Run install

From inside the cloned repo:

```
./setup/install.sh /absolute/path/to/your/talend-project
```

What it does, in order:

1. Sets `CIMT_TALEND_PATTERNS` to the absolute path of this repo, appended to (or replaced in) your shell rc (`~/.zshrc` on macOS, `~/.bashrc` on Linux). Single global value across all projects.
2. Creates symlinks (or junctions on Windows) from your project's `.claude/commands/` to this repo's `skills/`, and from `.claude/agents/` to this repo's `agents/`. Existing symlinks pointing to old locations are replaced; nothing else in `.claude/` is touched.
3. Drops `CLAUDE.md` into your project root if one doesn't exist. The integration block in the template is **pure copy-paste — nothing to fill in**. Add your own project sections (description, repo layout, git rules, user profile) above or below the block. If a `CLAUDE.md` already exists in the project, it is left untouched — the installer tells you which block to merge in from `templates/CLAUDE.md.template`.
4. Drops `.claude/talend.config.json` from the example template if one doesn't exist.

### Running on multiple Talend projects

The installer is **fully idempotent**. Run it once per project — re-running on the same project, or running on a second/third project, is safe and does not duplicate anything:

- The `CIMT_TALEND_PATTERNS` line in your shell rc is updated in place (single global).
- Symlinks are recreated cleanly per project.
- `CLAUDE.md` and `talend.config.json` are only created when missing — never overwritten.

Typical consultant setup with three Talend customer projects:

```
./setup/install.sh /work/customerA/talend-repo
./setup/install.sh /work/customerB/talend-repo
./setup/install.sh /work/customerC/talend-repo
```

After the third run you have three projects with their own `.claude/` symlinks pointing at the same `cimt-claude-talend` checkout. Each project's `CLAUDE.md` carries its own project-specific content around the shared integration block.

### Flags

| Flag | Effect |
|---|---|
| `--uninstall` | Removes symlinks from `<project>/.claude/`. Leaves `CLAUDE.md`, `talend.config.json`, and the shell-rc line alone. |
| `-h`, `--help` | Show usage. |

## Step 3 — Verify

```
./setup/doctor.sh
```

Checks:

- `CIMT_TALEND_PATTERNS` is set and points at a valid checkout
- All knowledge files referenced by skills exist
- All skill/agent symlinks resolve
- Python tools are runnable

Fix anything it flags.

## Step 4 — Per-project config

Inside your Talend project:

1. Copy `templates/talend.config.json.example` from this repo to `.claude/talend.config.json` in your project. Fill in `talendProjectName`, `p2UpdateUrl`, `tmc.publishUrl`, `tmc.workspace`. **This file is committed** — it's per-project, not per-developer.

2. In your project's `.claude/settings.local.json` (**gitignored**), add:

   ```json
   {
     "env": {
       "TALEND_STUDIO_PATH": "<absolute path to your Studio install>",
       "JAVA_HOME": "<absolute path to JDK 17 — Studio's bundled Zulu is fine>"
     }
   }
   ```

3. Per-session, export your TMC PAT in the shell where you'll run release commands:

   ```
   export TALEND_PAT="<your TMC PAT>"
   ```

   Never commit. Never write to disk.

## Step 5 — Project `CLAUDE.md`

The installer dropped `templates/CLAUDE.md.template` into your project as `CLAUDE.md` (if none existed). The integration block between the `START` and `END` markers is **pure copy-paste — nothing to fill in inside it**. Around the block, add the content your project needs Claude to know: project description, repo layout, project-specific conventions, git rules, user profile.

If a `CLAUDE.md` already existed in your project, copy the integration block from `templates/CLAUDE.md.template` and paste it somewhere in your `CLAUDE.md` (typical placement: after the project description, before deeper sections). Future upgrades = replace the whole block; nothing surrounding it is touched.

## Step 6 — Smoke test

In your project, ask Claude:

> "Wo finde ich die TMC microservice lifecycle Doku?"

Claude should locate `knowledge/tmc/microservice-lifecycle.md` via the env var and reply. If it can't, run `doctor.sh` again.

## Uninstall

```
./setup/install.sh --uninstall /path/to/your/talend-project
```

Removes symlinks. Does not touch your `CLAUDE.md` or `talend.config.json` (those belong to the project). The shell-rc line for `CIMT_TALEND_PATTERNS` remains — remove manually if no projects use it.
