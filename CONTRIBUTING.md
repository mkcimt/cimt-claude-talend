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
   - 4 → `~/.claude/CLAUDE.md` or the project's `.claude/settings.local.json`.

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

1. Fork or branch.
2. Add the knowledge file (or update an existing one).
3. Update `knowledge/INDEX.md` if you added a file.
4. Open a PR with a short rationale: which layer, where it came from, how it was verified.

For typos or small clarifications, a PR directly to `main` is fine.

## When Claude is in the loop

If you're working with Claude and a new insight pops up:

- Claude should propose a classification and a file location.
- You confirm or correct.
- Claude writes the file in the appropriate repo and commits on a feature branch.
- You decide when to push.

The Capture Discipline rule (in the project `CLAUDE.md` template) makes this routine, not exceptional.
