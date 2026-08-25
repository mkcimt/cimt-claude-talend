# Contributing

This kit grows when developers run into things — bugs, conventions, gotchas — and capture them in the right place. The single most important rule: **classify the finding's layer before deciding where to put it.**

## The capture flow

When you (or Claude on your behalf) hit a non-trivial Talend insight mid-work:

1. **Classify** the finding:
   - **Layer 2a** — true for any Talend project (mechanics, TMC behaviour, Studio quirks)?
   - **Layer 2b** — only true if the project uses a particular pattern (a framework, a component)?
   - **Layer 3** — only true for this project (conventions, business glossary, interface list)?
   - **Layer 4** — only true for this developer / laptop (paths, personal preferences)?

2. **Capture in the right place**:
   - 2a → this repo, in the matching `knowledge/...` file. New file if no existing one fits.
   - 2b → this repo, in `knowledge/patterns/...`. Document the variants and trade-offs.
   - 3 → the consuming Talend project's `docs/` and/or `CLAUDE.md`.
   - 4 → the project's `.claude/talend.local.properties` (paths, PAT) or your user memory (preferences).

3. **Memory is for Layer 4 only.** Anything that should survive a `rm -rf ~/.claude` belongs in a repo, not in memory.

## Why this rule matters

Memory is per-machine, per-workspace-path. It silently diverges between developers. Project-relevant knowledge that lives only in one developer's memory is invisible to teammates and to Claude itself when that developer is on a different laptop. Repo files are visible, reviewable, and survive machine changes.

## What to put in a Layer 2 knowledge file

A new `knowledge/` file should:

- Start with a one-sentence summary in `>` blockquote form.
- For **2a** files: declare the mechanic concisely. Include verification ("Verified on TMC EU R2025-12 …") for empirical claims.
- For **2b** files: structure as **Concept** → **Variants** → **Trade-offs** → **Project Overlay Slot** (the slot says how a consuming project declares which variant it uses).
- Cross-reference related files with relative links.
- Avoid project-specific examples. When an example is essential (e.g. a canonical bug pattern), anonymize it.

## What to put in a Layer 3 project doc

A project doc should:

- Reference Layer 2 files for mechanic explanation rather than duplicating them.
- Carry the business glossary, interface list, KEDB, naming conventions.
- Capture answers to ask-once questions (e.g. "are data services here deployed as microservices or as OSGi bundles?" — see `knowledge/tmc/deployment-modes.md`) so future sessions don't re-ask.

Note: project pattern choices for things like context-variable handling or batch frameworks are **not** declared in `CLAUDE.md` — they're detected from the project's artifacts. Each `knowledge/patterns/*.md` file lists the detection cues. See [`knowledge/INDEX.md`](knowledge/INDEX.md).

## How to propose a change here

This repo is currently maintained at [mkcimt/cimt-claude-talend](https://github.com/mkcimt/cimt-claude-talend). For meaningful additions:

1. Work on a feature branch in **your fork** — not in the kit checkout your projects consume. See the two checkouts below.
2. Add the knowledge file (or update an existing one).
3. Update `knowledge/INDEX.md` if you added a file.
4. Add a short entry to `CHANGELOG.md` under `## [Unreleased]` describing the change (Keep-a-Changelog format: `### Added`/`### Changed`/`### Fixed`/`### Removed`/`### Security`).
5. If the change closes a `BACKLOG.md` item, move that entry to the backlog's `## Done` section in the same PR.
6. Open a PR with a short rationale: which layer, where it came from, how it was verified.

For typos or small clarifications the same route applies — only the CHANGELOG entry can be skipped for cosmetic-only changes.

### The two checkouts

The checkout a project points at (`.claude/cimt-claude-talend.path`, e.g. `C:\dev\cimt-claude-talend`) is a **downstream** clone of this repo. Unless you have write access, you cannot push from it — and you should not want to: it is the copy your projects load skills and knowledge from, so leaving it on a feature branch breaks `setup/update.py` and confuses the next session.

Contributions go through a **fork**, cloned to a second folder (e.g. `C:\dev\forked\cimt-claude-talend`). Keep the two apart and the downstream copy always on `main`.

One-time setup:

1. Fork [mkcimt/cimt-claude-talend](https://github.com/mkcimt/cimt-claude-talend) on GitHub.
2. Clone the fork into its own folder, separate from the downstream checkout.
3. Optionally add the parent as a second remote so you can sync later: `git remote add upstream https://github.com/mkcimt/cimt-claude-talend.git`.

Your fork's `main` stays a mirror of upstream `main` — never merge a feature branch into it. After a PR is merged, sync with `git checkout main && git pull upstream main` and delete the feature branch.

### Per change — who does what

**Claude:**

1. Branch off the fork's `main` (`git checkout main && git pull` first if the fork has fallen behind — otherwise the PR needs a rebase later).
2. Apply the change, including the INDEX, CHANGELOG and BACKLOG upkeep from the list above.
3. Commit on the feature branch.
4. Push to the fork's `origin`.
5. Hand over a PR title and description covering layer, origin and verification.

**You:**

1. Open the fork on GitHub — the yellow "had recent pushes" banner appears after the push; click **Compare & pull request**.
2. Check the direction: **base repository** `mkcimt/cimt-claude-talend`, **base** `main` ← **head repository** `<you>/cimt-claude-talend`, **compare** `<branch>`. GitHub usually preselects this for a fork, but not always.
3. Paste the title and description Claude handed over.
4. **Create pull request.**

The split is not ceremony: Claude has neither a GitHub session nor, usually, the `gh` CLI, so it can push with your stored git credentials but cannot open the PR. If `gh` *is* installed and authenticated, Claude can do steps 1–4 of your half as well.

**Push credentials.** The push targets your own fork, so a classic personal access token with the `repo` scope is enough (`public_repo` suffices while the fork is public). With a fine-grained token, the fork must be listed under *Repository access* and **Contents** must be *Read and write* — a token created before you forked will not include the new repository and fails with `Permission to <you>/… denied to <you>`. Only if a commit touches `.github/workflows/` is the additional `workflow` scope (fine-grained: *Workflows: write*) needed.

## Releases (maintainer note)

We use SemVer with a `0.x.x` beta prefix. When cutting a release:

1. Move the `## [Unreleased]` entries in `CHANGELOG.md` under a new `## [X.Y.Z] — YYYY-MM-DD` heading.
2. Commit the changelog update.
3. `git tag -a vX.Y.Z -m "vX.Y.Z"` on the resulting commit, then `git push --tags`.
4. `gh release create vX.Y.Z --title "vX.Y.Z — <one-line summary>" --notes-from-tag` (or with the release notes pasted in).

## When Claude is in the loop

If you're working with Claude and a new insight pops up:

- Claude should propose a classification and a file location.
- You confirm or correct.
- Claude writes the file in the appropriate repo and commits on a feature branch.
- You decide when to push.

For a Layer 2a/2b finding, "the appropriate repo" is your fork of this one — see [Per change — who does what](#per-change--who-does-what) for the hand-off.

The Capture Discipline rule (in the project `CLAUDE.md` template) makes this routine, not exceptional.
