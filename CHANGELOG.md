# Changelog

All notable changes to **cimt-claude-talend** are documented here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Beta.** While the version is `0.x.x`, minor releases may contain breaking changes. From `1.0.0` onward, only major versions will.

## [Unreleased]

### Added

- **`knowledge/mechanics/item-editing-programmatic.md`** — hard rules and pre-edit checklist for editing `.item` files from outside Studio. Documents the CRLF-on-Windows requirement (which Python `Path.write_text` silently violates), `<elementParameter>`-internal id uniqueness when cloning blocks, UTF-8-without-BOM, and embedded-entity (`&#xD;&#xA;`, `&#13;&#10;`, `&#x9;`) preservation. Includes verification snippets to run after every write.
- **`knowledge/mechanics/joblet-inlining.md`** — Talend joblets are inlined templates, not function calls. Documents the multiplication formula (`N_invocations × N_components`), the JDT-formatter-OOM threshold (~30 MB generated `.java` at 4 GB heap), and the Joblet → Job refactoring trade-off when a route's generated code is bloating.
- **`knowledge/mechanics/studio-clean-and-codegen.md`** — Talend Studio has no Project → Clean menu. Documents the four ways to force a regenerate (manual cache wipe, Code tab, `mvn clean`, `-Dtalend.studio.m2.clean=true`) and the diagnostic flow for `processCode is null` — which is almost always a downstream symptom of an OOM or generator failure logged earlier in `.metadata/.log`.

### Changed

- **`templates/CLAUDE.md.template` — editing protocol section rewritten.** Was: a one-paragraph rule about touching `.properties`. Now: five numbered hard rules covering line endings, id uniqueness, entity preservation, and post-edit verification, plus pointers to the three new mechanics docs. Adopters refresh the integration block by re-running `setup/install.py` (or `setup/update.py`).

### Fixed

- **`doctor.py` no longer crashes on Windows consoles with cp1252.** The report contains characters like `→` that the default Windows code page can't encode. `main()` now reconfigures `sys.stdout`/`sys.stderr` to UTF-8 (errors=replace) before any output.
- **`doctor.py` now recognises Windows directory junctions as kit links.** `_is_windows_junction()` previously called `path.stat()`, which follows the junction and returns the target's metadata (no `st_reparse_tag`), causing junctions to be reported as "regular directory, not a kit link". Switched to `os.lstat()` so the reparse tag of the link itself is checked.

## [0.3.0] — 2026-05-18

### Added

- **`.claude/tmp/` scratch-file convention.** All temporary scripts, JSON dumps, intermediate reports, and one-off helpers Claude generates during a session now go into `.claude/tmp/` in the project root, which is gitignored and invisible to Talend Studio's Git Staging view. The CLAUDE.md template instructs Claude to use this location; `install.py` patches the entry into existing projects' `.gitignore` on re-run. Full rationale + migration guidance for projects that already have scattered scratch files in `knowledge/mechanics/scratch-files.md`.

### Fixed

- `install.py` now adds `CLAUDE.md.bak.*` to the default `.gitignore` entries — the timestamped backups it creates when refreshing the integration block are local recovery files and should not appear in `git status`.

## [0.2.0] — 2026-05-13

The first substantive release after the initial repo bootstrap. The kit has been refactored around three principles: **cross-platform Python tooling** replacing macOS-only bash, **.properties config** replacing JSON, and **Claude-driven UX** where the user runs bootstrap once and Claude handles config discovery, PAT entry, updates, and doctor afterwards.

### Added

- **Python setup scripts** — `install.py`, `doctor.py`, `bootstrap.py`, `store_pat.py`, `update.py`. Stdlib-only. Cross-platform: directory junctions on Windows via `mklink /J` (no admin/dev-mode needed), `setx` for the env var, thin PowerShell + bash shims around `bootstrap.py`.
- **`.properties` config** — `talend.properties` (project-shared, committed) and `talend.local.properties` (per-developer, gitignored). Templates ship in `templates/`. `tools/cli.py` provides get/set/list for Claude to drive interactively; routes keys to the right file automatically. Shared `tools/properties.py` parses/writes with comment and key-order preservation, atomic writes.
- **Marker file** `.claude/cimt-claude-talend.path` written by install — the primary mechanism by which Claude locates the kit. Survives Windows shell-rc weirdness (cmd vs. PowerShell vs. Git Bash); env var is the secondary fallback.
- **Pre-flight path validation** — `install.py` checks the given path looks like a Talend project root (contains a subfolder with a `talend.project` file). If not, fails fast and *suggests the correct path*: if the user gave the Studio workspace folder → lists the inner project folders; if the user gave the Talend project folder (one level too deep) → suggests its parent.
- **Auto-refresh of the CLAUDE.md integration block** on `install.py` re-run. Locates the kit-managed region by its `START`/`END` markers and replaces it with the current template. Content outside the block is untouched. A backup (`CLAUDE.md.bak.<timestamp>`, last 3 kept) is written before any change.
- **`update.py <project>`** — one-command update: `git pull` plus immediate refresh of the project (`install.py` re-run on it). With no argument, just pulls and points at the next step.
- **New knowledge files** — `mechanics/operational-vs-documentation.md` (read-live principle for ops commands), `tmc/deployment-modes.md` (microservice-on-Remote-Engine vs. OSGi-on-Runtime, the one project-level choice not derivable from artifacts).
- **`BACKLOG.md`** for tracking ideas (OS keychain for PAT, auto-derive `p2.update.url`, document-interface joblet awareness, diff-only review handoff).
- **README "About" section** naming Mirco Kriesten / cimt as maintainers, with contact paths (issues, email, [cimt-ag.de](https://www.cimt-ag.de) / [cimt.nl](https://www.cimt.nl)).
- **`.gitignore` defaults** managed by install — `.claude/commands`, `.claude/agents`, `.claude/settings.local.json`, `.claude/talend.local.properties`, `.claude/cimt-claude-talend.path`, plus `worktrees/` and `.worktrees/` to keep accidental worktree folders out of git. Also untracks any legacy tracked `.claude/commands/` or `.claude/agents/` files (pre-kit setups).

### Changed

- **Project config moved from JSON to `.properties`.** The old `.claude/talend.config.json` is removed by install on first run; the user is not asked to migrate values, Claude fills them on first need.
- **CLAUDE.md template restructured.** Kit-managed block is bounded by visible blockquote `START`/`END` markers (was HTML comments) — boundary visible in any markdown viewer. The block now includes explicit kit-location discovery rules (marker file → env var → STOP), configuration discovery (read → derive from artifacts → ask with context → persist via `cli.py`), `.item` editing protocol, capture discipline, operational-vs-documentation principle, doctor-on-first-use, and update orchestration.
- **Pattern Selection removed from `CLAUDE.md`.** Talend's artifacts make patterns visible (typed components, conventional names); pre-declaration added drift risk without information value. The exception (data-services deployment mode) is handled via ask-once-and-persist.
- **PAT entry.** Primary path is now: user pastes in chat → Claude stores via `cli.py set` → confirms `"PAT stored."`. `setup/store_pat.py` becomes the terminal-only fallback for users who prefer hidden-input prompts.
- **README** leads with the Windows install command (majority of users); Claude-first phrasing throughout (doctor/update presented as natural-language prompts, CLI alternatives in collapsible blocks).
- **GitHub owner** transferred from `ElRakiti` to `mkcimt`. All internal references updated; LICENSE copyright corrected.

### Fixed

- **Idempotent install re-run on Windows.** Existing junctions in `.claude/commands` and `.claude/agents` are removed via `rmdir` fallback when `unlink` doesn't suffice (older Python on Windows doesn't always recognise junctions as symlinks).
- **`.gitignore` entries for symlinked `.claude/commands` and `.claude/agents`** are written without trailing slashes — a trailing slash means "directory only" and does not match symlinks-to-directories. The earlier version silently let the kit's symlinks slip into git as mode-120000 entries pointing at developer-local absolute paths.
- **Kit discovery on Windows.** PowerShell-profile env vars are not visible to cmd / Git Bash, so Claude couldn't find the kit and resorted to scanning the disk. The new marker-file + `setx` combination makes the kit visible from any shell type.

### Security

- Initial-release commit reset to a single orphan commit with no inherited history (the kit was extracted from a customer Talend project; the rewrite removed all customer-specific identifiers, port tables, TMC task IDs, hard-coded URLs from working tree and commit messages).
- `.gitignore` covers `.claude/settings.local.json` (where TMC PAT may appear inline in permission strings) and `.claude/talend.local.properties` (where PAT and paths live).

## [0.1.0] — 2026-05-12

Initial release. The kit was extracted from the in-project `cimt-talend/` folder of a customer Talend project and reorganised around the four-layer model (Qlik docs, universal Talend mechanics, optional patterns, project-specific, developer-specific). Single orphan commit; no inherited history.
