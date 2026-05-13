# cimt-claude-talend

**A drop-in extension that makes [Claude Code](https://www.anthropic.com/claude-code) work properly on Qlik Talend Studio projects.**

> ⚠ **Beta — in active testing.** Things will change. Some sharp edges are expected. Feedback welcome via Issues.

Out of the box, Claude knows generic Talend the way someone who skimmed the docs would. It doesn't know how to efficiently read the 10 000-line `.item` XML files Studio produces, doesn't know which TMC API endpoints have undocumented bugs (and how to work around them), can't tell apart a real functional change from Studio's autosave noise in a branch diff, and won't follow any of the conventions a real Talend team has built up over the years.

This repo gives Claude that missing context, plus a small set of ready-made commands for the everyday Talend tasks. **You install it once per Talend project, then everything else happens through Claude** — config questions, PAT entry, health checks, updates. After the initial setup you don't touch the kit's scripts again unless you want to.

---

## 5-minute setup

You need: **Python 3.9+**, **git**, and **Claude Code** installed. That's it.

> **Which folder is "your Talend project"?** The folder that contains your project as a git repository — usually one level *inside* your Talend Studio workspace, **not** the workspace folder itself. The right folder has a subfolder with a `talend.project` file inside it.
>
> Example layout (Windows, names are illustrative):
>
> ```
> C:\Talend\Talend-Studio-Shimano\workspace\        ← Studio workspace (NOT this one)
>   └── talend-dare-816295992\                      ← your project (THIS one — has .git/)
>         ├── .git\
>         ├── MY_TALEND_PROJECT\
>         │     └── talend.project                  ← Talend's project descriptor
>         └── docs\
> ```
>
> If you pick the wrong level, the installer says so and suggests the right one.

Run **one command** (pick your shell):

```powershell
# Windows (PowerShell)
git clone https://github.com/mkcimt/cimt-claude-talend.git C:\dev\cimt-claude-talend
C:\dev\cimt-claude-talend\setup\bootstrap.ps1 C:\Talend\Talend-Studio-Shimano\workspace\talend-dare-816295992
```

```bash
# macOS / Linux
git clone https://github.com/mkcimt/cimt-claude-talend.git ~/dev/cimt-claude-talend && \
  ~/dev/cimt-claude-talend/setup/bootstrap.sh /absolute/path/to/your/talend-project
```

The bootstrap script:
1. Clones the companion [`claude-qlik-docs`](https://github.com/mkcimt/claude-qlik-docs) repo next to this one (only if not already there).
2. Sets the `CIMT_TALEND_PATTERNS` environment variable.
3. Links this kit's skills and agents into your project's `.claude/` folder.
4. Creates `CLAUDE.md`, `.claude/talend.properties`, `.claude/talend.local.properties` from templates if they don't exist.
5. Updates `.gitignore` with the necessary entries.

**Open Claude Code in your project and start working.** Claude will ask for any missing config values (paths, tokens) the first time it needs them.

If anything looks off, **just ask Claude** — *"check the cimt-claude-talend setup for this project"*. Claude runs the health check, surfaces any problems, and offers to fix them.

<details>
<summary>If you'd rather run the check yourself (CLI)</summary>

```bash
~/dev/cimt-claude-talend/setup/doctor.py /absolute/path/to/your/talend-project
```

</details>

---

## What's in here

```
knowledge/        Markdown reference material, loaded on demand by Claude.
                  See knowledge/INDEX.md for the table of contents.
skills/           Slash commands (review-talend-branch, review-talend-code,
                  document-interface). Linked into your project's .claude/commands/.
agents/           Subagents used by the slash commands. Linked into .claude/agents/.
tools/            Python CLIs (tmc_release.py, tmc_microservice_ops.py,
                  touch_item_properties.py, cli.py for config get/set).
templates/        Drop-in starting points for the consuming project.
                  - CLAUDE.md.template — project-overlay skeleton (drop-in fixed block).
                  - talend.properties.example — project-shared config (committed).
                  - talend.local.properties.example — per-developer config (gitignored).
setup/            bootstrap.py + bootstrap.{sh,ps1}, install.py, doctor.py,
                  store_pat.py, update.py. All Python, cross-platform.
BACKLOG.md        Ideas and improvements we'd want eventually.
```

## What ends up in your Talend project

After bootstrap, your Talend project gets:

| File / dir | Who owns it | In git? | Purpose |
|---|---|---|---|
| `CLAUDE.md` | you and your team | yes | Loaded by Claude at session start. Project description + a fixed integration block. |
| `.claude/commands/` | this kit | no | Slash commands. A shortcut that points to the kit, so updates to the kit show up automatically. |
| `.claude/agents/` | this kit | no | Subagents. Same shortcut idea as `commands/`. |
| `.claude/talend.properties` | your team | **yes** | Project-shared config: project name, TMC region/workspace, etc. |
| `.claude/talend.local.properties` | you | no | Per-developer config: Studio path, framework path, PAT. |
| `.claude/settings.local.json` | Claude Code itself | no | Claude's permission allowlist, env vars. Not managed by this kit. |

## What it does *not* do

It does not modify your Talend project's source code, run anything automatically, or send anything anywhere without you asking. It's a passive context layer plus on-demand commands.

---

## How it works in one paragraph

Claude Code can read markdown files on demand and run skills (slash commands you trigger with `/`). This repo provides both: a folder of carefully written markdown documents that Claude reads when a Talend topic comes up, and a folder of skill definitions you can invoke directly. The bootstrap script junctions those folders into your Talend project's `.claude/` and sets an environment variable that points Claude at the knowledge base. Everything is local — no server, no service, just files.

---

## Example prompts

The slash commands `/document-interface`, `/review-talend-branch`, `/review-talend-code` exist for workflows that benefit from a wrapper. **Most everyday work is free-form natural language**, because Claude already knows Talend from the knowledge base:

- **Reading and understanding a job** — *"Walk me through what job iXYZ does."* / *"What reject paths does this worker have?"* / *"Trace the call chain from the deployed job."*
- **Investigating TMC state** — *"Which artifact version of task iXYZ is currently deployed on tst?"* / *"Why is the deploy of iABC on uat failing?"* / *"List all i5xx microservices that are not running on prd."*
- **Build, publish, deploy** — *"Build job iXYZ and publish it to dev."* / *"Promote all i5xx APIs from tst to uat."* / *"Redeploy iABC on tst — it's stuck on the old artifact."*
- **Editing with the right safety net** — *"Update the SQL query in `mod_order_validation` so that `request_to_move_up` is also taken into account."* (Claude edits the `.item` *and* touches the sibling `.properties` in the same commit, because that's a hard rule it knows from `CLAUDE.md`.)
- **Conversational review** — *"Take a look at my latest changes on `feature/x`."* (Claude can do this without `/review-talend-branch` — it knows to filter Studio noise because the convention is in `knowledge/`.)

---

## Talking to Claude about setup itself

You can also ask Claude to do the setup chores for you:

- *"Update cimt-claude-talend."* → Claude runs `setup/update.py`, tells you if a session restart is needed.
- *"Run the doctor on this project."* → Claude runs `setup/doctor.py <project>`, surfaces issues with fix hints.
- *"My TMC operations need a new PAT — store it."* → Claude runs `setup/store_pat.py <project>` and you paste the token into the prompt (no echo).
- *"Set my Talend Studio path."* → Claude asks for the path, then writes it via `tools/cli.py set`.

You only need to run the bootstrap manually because the kit doesn't exist yet when you start. Everything else, Claude can drive.

---

## The four-layer model (skip if you don't care)

This kit is organized around a deliberate split between what's universal and what's project-specific:

| Layer | What it is | Where it lives |
|---|---|---|
| **1** — Qlik official docs | Authoritative Qlik Talend documentation | [`claude-qlik-docs`](https://github.com/mkcimt/claude-qlik-docs) (separate skill, installed automatically by bootstrap) |
| **2a** — Universal Talend mechanics | How `.item` files work, Studio quirks, TMC API behaviour, git workflow alongside Studio | This repo — `knowledge/mechanics/`, `knowledge/tmc/`, `knowledge/build-publish/`, `knowledge/code-review/`, `knowledge/documentation/` |
| **2b** — Optional patterns | Components and frameworks a project may or may not use (Job Instance Framework, `tContextLoad`, …). Variant in use is **detected from the project's artifacts** at the moment it becomes relevant. | This repo — `knowledge/patterns/` |
| **3** — Project-specific knowledge | Conventions, business glossary, interface list, known errors | The consuming Talend project's own repo, typically `docs/` and `CLAUDE.md` |
| **4** — Developer/laptop-specific | Local checkout paths, personal preferences, secrets | `.claude/talend.local.properties` and user memory |

If a finding is true for *any* Talend project → Layer 2 (here). If it's only true for *this* project → Layer 3 (the project's own repo). If it's only true on *this developer's machine* → Layer 4 (local properties or user memory). [`CONTRIBUTING.md`](CONTRIBUTING.md) walks through how to capture new findings in the right place.

---

## Updating

Just tell Claude: *"update cimt-claude-talend"*. Claude pulls the latest and tells you whether a session restart is needed (knowledge files load automatically; skill/agent changes need a restart).

<details>
<summary>CLI alternative</summary>

```bash
~/dev/cimt-claude-talend/setup/update.py
```

</details>

---

## Uninstalling from one project

```bash
~/dev/cimt-claude-talend/setup/install.py --uninstall /absolute/path/to/your/talend-project
```

Removes the symlinks. Leaves `CLAUDE.md` and `talend.properties` alone (those are your project's files now). The shell-rc `CIMT_TALEND_PATTERNS` line stays — remove it manually if no projects use the kit any more.

---

## About

cimt-claude-talend is built and maintained by **Mirco Kriesten** at **cimt** — an IT consulting firm with a focus on data integration, data management, data governance, BI, and the Talend platform. The kit grew out of cimt's day-to-day work running and modernising customer Talend installations: the conventions, the TMC bug workarounds, the Studio reading patterns are all empirically earned.

**Getting in touch:**

- **Bugs or feature ideas** — open an issue on this repo.
- **Questions about the kit, or about using Claude Code with Talend in general** — [mirco.kriesten@cimt-ag.de](mailto:mirco.kriesten@cimt-ag.de).
- **Looking for professional support** — Talend implementation, migration, managed services, or any of the wider data management / data governance / BI / cloud data platform topics — see **[cimt-ag.de](https://www.cimt-ag.de)** (DE) / **[cimt.nl](https://www.cimt.nl)** (NL), or reach out directly.

If you find this useful at a customer engagement: a mention or a link back is appreciated.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Releases are tagged on GitHub — watch the repo or check the [Releases page](https://github.com/mkcimt/cimt-claude-talend/releases) to know when something new lands.

## License

MIT — see [LICENSE](LICENSE).
