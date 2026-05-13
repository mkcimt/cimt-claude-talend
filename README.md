# cimt-claude-talend

**A drop-in extension that makes [Claude Code](https://www.anthropic.com/claude-code) work properly on Talend Studio projects.**

Out of the box, Claude knows generic Talend the way someone who skimmed the docs would. It doesn't know how to efficiently read the 10 000-line `.item` XML files Studio produces, doesn't know which TMC API endpoints have undocumented bugs (and how to work around them), can't tell apart a real functional change from Studio's autosave noise in a branch diff, and won't follow any of the conventions a real Talend team has built up over the years.

This repo gives Claude that missing context, plus a small set of ready-made commands for the everyday Talend tasks — documenting an interface, reviewing a branch, building and publishing an API to TMC, deploying and promoting microservices. You install it once per Talend project and Claude immediately behaves like someone who has worked in that project for years.

---

## Install alongside `claude-qlik-docs`

Before you install this kit, also install [**`claude-qlik-docs`**](https://github.com/mkcimt/claude-qlik-docs). It exposes the official Qlik Talend documentation as a Claude Code skill so Claude can look things up authoritatively. The two repos are designed to work together — `claude-qlik-docs` answers *"what does Qlik officially say"*, this repo answers *"what have we learned doing the actual work"*. Without both, Claude is missing half the picture.

Two separate clones, two separate installers — see each repo's README.

---

## What you actually get

Two things, in order of importance:

### 1. A knowledge base Claude consults automatically

A folder of short, focused markdown documents covering everything Claude needs to be useful in a Talend project — how `.item` files are structured and how to read them efficiently, the TMC public API and the empirically-found bugs (with workarounds), Maven build internals, Studio noise patterns to filter out of diffs, code-review principles tuned for Talend, interface-documentation conventions. Claude pulls these in on demand whenever a relevant topic comes up. This is the part that does the heavy lifting — it's what makes Claude *informed* about Talend, not just superficially familiar.

You don't run the knowledge base; it sits there and Claude reads from it. See `knowledge/INDEX.md` for the full table of contents.

### 2. Slash commands for the most common Talend tasks

Ready-made workflows you can trigger explicitly:

- `/document-interface i562` — Claude reads the deployed jobs, asks a couple of upfront questions, and writes a clean per-interface document under `docs/interfaces/`.
- `/review-talend-branch` — Claude reviews the current feature branch, filters out Studio noise (UI coordinates, screenshot binaries, version bumps), surfaces real functional risks, and proposes a clean commit message.
- `/review-talend-code <scope>` — focused review on a specific file, folder, or interface ID with severity-classified findings (Blocker / Warning / Nit).

These exist because the workflows behind them are involved enough that wrapping them in a single command is worth it. **Most of your interaction with Claude won't use them** — see the example prompts below.

### …and the supporting cast

- **Python release tooling** that wraps TMC's API and handles the bugs we've found empirically (`tools/tmc_release.py`, `tools/tmc_microservice_ops.py`). Claude calls these directly when you ask to publish, bind, promote, or deploy.
- **A project template** (`templates/CLAUDE.md.template`) — see next section.

What it does *not* do: it does not modify your Talend project's source code, it does not run anything automatically, it does not send anything to anywhere without you asking. It's a passive context layer plus on-demand commands.

---

## The `CLAUDE.md` in your project is the linchpin

Both the knowledge base and the slash commands are *available* once you install this kit — but Claude needs to know they exist, when to use them, and which Talend patterns your specific project follows. That's what your project's `CLAUDE.md` does: it's the file Claude Code reads at the start of every session, and it tells Claude:

- where the `cimt-claude-talend` knowledge base lives on this machine (via the `CIMT_TALEND_PATTERNS` env var),
- the hard rules Claude must follow (e.g. *"when you edit a `.item`, also update the sibling `.properties` in the same commit"*),
- the capture discipline — where new findings get filed (this kit, your project's `docs/`, or local memory),
- any project-specific conventions that override or augment the defaults (these go *outside* the fixed integration block — you maintain them per project).

The installer drops a minimal `CLAUDE.md.template` into your project the first time it runs. The template is intentionally short and has a *fixed block* you don't change — everything project-specific (your project description, repo layout, git rules, user profile) goes above or below that block. If you already had a `CLAUDE.md`, the installer tells you what to merge in.

In practice: **without a properly configured `CLAUDE.md`, you'll have the knowledge base sitting on disk and Claude won't know to use it.** Treat the `CLAUDE.md` as the central file for adopting this kit.

---

## How it works in one paragraph

Claude Code can read markdown files on demand and run "skills" (slash commands you trigger with `/`). This repo provides both: a folder of markdown documents Claude reads when a Talend topic comes up, and a folder of skill definitions invocable directly. The install script symlinks the skills into your Talend project's `.claude/` folder (so Claude Code sees them as native) and sets an environment variable that points Claude at the knowledge base. Everything is local — no server, no service, just files.

---

## Use it with your Talend project

You need: Python 3.9+, [Claude Code](https://www.anthropic.com/claude-code) installed, and a Talend Studio project checked out somewhere. Optionally Maven 3.9+ / JDK 17 if you want to run builds, and a Talend Personal Access Token if you want to use the TMC operations. And: `claude-qlik-docs` installed (see top of this README).

### 1. Clone this repo

Put it *outside* your Talend project — it's a shared toolkit, not a sub-folder of any one project.

```bash
# macOS / Linux
git clone https://github.com/mkcimt/cimt-claude-talend.git ~/dev/cimt-claude-talend

# Windows (PowerShell)
git clone https://github.com/mkcimt/cimt-claude-talend.git C:\var\opt\cimt-claude-talend
```

### 2. Run the installer pointing at your Talend project

```bash
~/dev/cimt-claude-talend/setup/install.sh /absolute/path/to/your/talend-project
```

What it does:

- writes `export CIMT_TALEND_PATTERNS=...` into your shell rc (so Claude finds the knowledge base from any session),
- creates symlinks from `<your-project>/.claude/commands/` and `<your-project>/.claude/agents/` into this repo,
- drops a `CLAUDE.md` into your Talend project if you don't have one yet — the integration block is pure copy-paste, nothing to fill in; you add your own project sections (description, repo layout, git rules, user profile) above or below it,
- drops a `talend.config.json` template into `<your-project>/.claude/` for the TMC release tooling.

**The installer is idempotent and safe to run on multiple projects.** Each invocation creates / refreshes the symlinks in that project's `.claude/` and never overwrites an existing `CLAUDE.md` or `talend.config.json`. Consultants juggling several Talend projects just run the command once per project — the env var stays the same, only the symlinks differ.

Want to undo? `setup/install.sh --uninstall /path/to/project` removes the symlinks. The `CLAUDE.md` and `talend.config.json` it created are left alone (they're your project's files now).

### 3. Verify

```bash
~/dev/cimt-claude-talend/setup/doctor.sh /absolute/path/to/your/talend-project
```

It checks that everything's wired up, that knowledge files load, that Python tools are reachable.

### 4. Try it

Open Claude Code in your Talend project. See the examples below. The fixed integration block in `CLAUDE.md` is the only thing the kit needs to function — Claude detects which optional Talend patterns this project uses (built-in context groups vs. external framework repo, etc.) by reading the project's artifacts on demand, not from a pre-declared pattern list.

---

## Example prompts

*Placeholder — concrete examples will be added once we've collected a representative set from real sessions. The intent: show that everyday usage is mostly free-form natural language, not slash commands.*

Categories we want to cover:

- **Reading and understanding a job** — *"Walk me through what job iXYZ does."* / *"What reject paths does this worker have?"* / *"Trace the call chain starting from the deployed job for iABC."*
- **Investigating TMC state** — *"Which artifact version of task iXYZ is currently deployed on tst?"* / *"Why is the deploy of iABC on uat failing?"* / *"List all i5xx microservices that are not running on prd."*
- **Build, publish, deploy** — *"Build job iXYZ and publish it to dev."* / *"Promote all i5xx APIs from tst to uat."* / *"Redeploy iABC on tst — it's stuck on the old artifact."*
- **Editing with the right safety net** — *"Update the SQL query in `mod_order_validation` so that `request_to_move_up` is also taken into account."* (Claude edits the `.item` *and* touches the sibling `.properties` in the same commit, because that's a hard rule it knows from `CLAUDE.md`.)
- **Conversational review** — *"Take a look at my latest changes on `feature/x`."* (Claude can do this without `/review-talend-branch` — it knows to filter Studio noise because the convention is in `knowledge/`.)

The slash commands `/document-interface`, `/review-talend-branch`, `/review-talend-code` exist for workflows involved enough to benefit from a wrapper. Most everyday work is the free-form prompts above.

---

## The four-layer model (if you care about why things are where they are)

This kit is organized around a deliberate split between what's universal and what's project-specific:

| Layer | What it is | Where it lives |
|---|---|---|
| **1** — Qlik official docs | Authoritative Qlik Talend documentation | [`claude-qlik-docs`](https://github.com/mkcimt/claude-qlik-docs) (separate skill, install alongside) |
| **2a** — Universal Talend mechanics | How `.item` files work, Studio quirks, TMC API behaviour, git workflow alongside Studio | This repo — `knowledge/mechanics/`, `knowledge/tmc/`, `knowledge/build-publish/`, `knowledge/code-review/`, `knowledge/documentation/` |
| **2b** — Optional patterns | Components and frameworks a project may or may not use (Job Instance Framework, `tContextLoad`, …). Variant in use is **detected from the project's artifacts** at the moment it becomes relevant; each pattern file documents the detection cues. | This repo — `knowledge/patterns/` |
| **3** — Project-specific knowledge | Conventions, business glossary, interface list, known errors, pattern choices | The consuming Talend project's own repo, typically `docs/` and `CLAUDE.md` |
| **4** — Developer/laptop-specific | Local checkout paths, personal preferences | `~/.claude/CLAUDE.md` or `<project>/.claude/settings.local.json` |

If a finding is true for *any* Talend project → Layer 2 (here). If it's only true for *this* project → Layer 3 (the project's own repo). If it's only true on *this developer's machine* → Layer 4 (user memory or local settings). `CONTRIBUTING.md` walks through how to capture new findings in the right place.

---

## What's in this repo

```
knowledge/        Markdown reference material, loaded on demand by Claude.
                  See knowledge/INDEX.md for the table of contents.
skills/           Slash commands (review-talend-branch, review-talend-code,
                  document-interface, …). Symlinked into the project's .claude/commands/.
agents/           Subagents used by the slash commands. Symlinked into the
                  project's .claude/agents/.
tools/            Python CLIs (tmc_release.py, tmc_microservice_ops.py,
                  touch_item_properties.py). Called by Claude and by skills.
templates/        Drop-in starting points for the consuming project.
                  - CLAUDE.md.template — project-overlay skeleton with fixed block
                  - talend.config.json.example — per-project TMC config
setup/            Install / uninstall / doctor scripts.
```

---

## Updating

```bash
cd ~/dev/cimt-claude-talend && git pull
```

Markdown knowledge files are picked up on the next Claude read — no restart needed. Skill / agent files are loaded at Claude Code session start, so restart the Claude session after pulling those.

---

## Contributing

When you learn something during work that turned out to be useful, capture it where it belongs:

- Universal Talend / TMC truth → a new file or addition under `knowledge/...`, PR here.
- Project-specific → that project's `docs/` and `CLAUDE.md`.
- Personal / machine-specific → your user memory or `.claude/settings.local.json`.

`CONTRIBUTING.md` has the full flow, including a checklist for new `knowledge/` files.

---

## License

MIT — see [LICENSE](LICENSE).
