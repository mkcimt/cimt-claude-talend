---
description: Author or refresh per-interface business + technical documentation under docs/interfaces/. Asks upfront questions, then iteratively analyses the deployed jobs.
argument-hint: [interface-id]
---

Document interface `$1`. If `docs/interfaces/$1.md` already exists, run in update-diff mode automatically. Otherwise, write a new doc.

This command runs **interactively in the main chat** — no subagent. The work is a dialogue with the user: analyse `.item` files, ask business-semantics questions, draft, iterate.

## Step 1 — Determine mode

- `$1` empty → ask which interface.
- `docs/interfaces/$1.md` missing → **new-doc mode**.
- `docs/interfaces/$1.md` exists → **update-diff mode**. Tell the user you'll refresh the existing doc; ask only if he prefers a full rewrite instead.

## Step 2 — Determine flavour

- ID matches `i5xx` **or** `process/i5xx_apis/<id>_*` exists → **API mode** (Talend Data Services microservice). Locate the matching Swagger artifact in `<TALEND_PROJECT>/metadata/dsrest/*.json`.
- Otherwise → **batch mode**.

## Step 3 — Load the convention

Read `docs/conventions/interface-documentation.md`. It defines both templates (batch + API), the upfront questions per flavour, the citation rule (job name in prose, file path in the citation table), shared-helper handling, review-findings handling, and the model heuristic. Follow it.

## Step 4 — Ask the upfront questions

Per the convention, using the question set for the detected flavour. Wait for the user's answers before reading any `.item`. Always refer to jobs by **job name only** in the questions and in the dialogue — no `_0.1.item` suffixes.

In **update-diff mode**, skip the *Deployed jobs* and *Triggering* questions if the existing doc's §2 (Technical Overview) already covers them — re-confirm only if the user signals the deployment changed.

## Step 5 — Decide on model

Based on the answers, evaluate complexity per the convention's "Model selection" table. If Opus is the right call but the current session is on Sonnet (or vice versa), say so explicitly so the user can `/model` switch before the heavy reading starts. Otherwise just proceed.

## Step 6 — Analyse iteratively

Walk the `.item` files starting from the deployed top-level / API jobs. For each:

- Anchor with `Grep` on `UNIQUE_NAME`, component names, query fragments — don't read 10k-line `.item` files end-to-end unless necessary.
- Trace `tRunJob` calls to map the internal call chain.
- Read the worker job(s) where the core business logic sits.
- For batch jobs: locate the central tMap(s) feeding the upsert/insert output and walk **every output column expression**, bucketing per the convention's "Deriving §5 from tMap output expressions" table. This is the source of the §5 subsections — Field Normalisations, Field-Name Translations, Mappings, Calculations, Enrichment, Fixed Values, Retained-on-Update. Don't skip this step; the literal-`null` and `row1.field` patterns are easy to miss otherwise.
- Resolve `context.getProperty("...")` against the external configuration framework checkout (path is developer-specific — see `CLAUDE.md` / local memory) whenever the value is part of the business rule (status enums, customer codes, mapping object types). See the convention's "Resolving `context.getProperty`" section.
- When business semantics are unclear (status code meaning, fallback rationale, retained fields), **ask the user**. Do not guess.
- In prose with the user, refer to jobs by **job name only**. Keep the file paths inkl. version internal — gather them for the final citation table.

**API mode additions:**

- Read the matching Swagger JSON (`<TALEND_PROJECT>/metadata/dsrest/*.json`). Extract endpoints + query/path params from there.
- Cross-check Swagger endpoints against the implementation. Endpoints + query params should align; mismatches go into the doc's "Known Drift / Open Issues" section. Do **not** document request/response object schemas — readers can look at the Swagger or the job directly.
- Trace into `code/routines/`, `joblets/`, `routelets/` to identify shared helpers (typical names: `QueryParser`, `Util`, `AuthManager`, similar). For each cross-cutting concern (auth, query parsing, row filter, column filter), note: shared or bespoke?
- Confirm the helper list with the user before writing — naming and intent are not always obvious. This is iterative: each new API doc improves the shared mental map.
- Document **how the SELECT (or update) is actually composed** beyond user query params — auth filtering, implicit row filters, column-level masking. A pseudo-SQL "result shape" is welcome.

**While reading, collect review findings** (perf issues, bugs, smells) in a side list — do **not** put them into the doc. They're reported separately at the end (Step 8b). **Exception:** functional gaps that change how the API contract behaves (incomplete validation guards, ignored enum values, bypassable auth checks) belong in §6 of the doc — see the convention's "Review findings" section.

For **update-diff mode**: re-read only the deployed / API jobs and focus on the "subject to change" areas listed in the convention. Don't re-derive stable sections (Purpose, Basic Principle) unless explicitly asked.

## Step 6b — Completeness pass (code-review via talend-code-reviewer)

**Default behaviour by mode:**
- New-doc mode: code-review pass is **ON** by default.
- Update-diff mode: code-review pass is **OFF** by default.

At the start of Step 6b, ask the user whether to run the code-review pass:
- New-doc: ask with default Y.
- Update-diff (only if the user explicitly raised the topic): ask with default N.

**When the pass runs:** delegate to the **talend-code-reviewer** subagent via the Agent tool. Pass:
- Scope: the interface ID (e.g. `i562`) — the agent resolves all deployed jobs and joblets.
- Context tag: `deployed-api-job`.

Do not run this pass inline — always delegate to the subagent.

Forward the subagent's findings:
- Contract-affecting findings (incomplete validation guards, missing change fields, ignored enum values, bypassable auth checks) → surface in the doc's §6 (Known Drift / Open Issues).
- Other findings (perf, smells, dead code, naming) → out-of-band review list, reported in Step 8b.

**If the subagent surfaces 0 findings on a substantial scope (> 5 files),** add an entry to `.claude/CHANGELOG.md` under "Offene Punkte":
```
- <date> — <interface>: code-reviewer surfaced 0 findings on <N> files — sanity check worthwhile?
```

## Step 7 — Draft and confirm

Show the user the draft (or proposed delta for update-diff) **before** writing the file. Iterate on his feedback. The draft uses job names in body text; the final "Where to look" table is the single place where file paths inkl. version appear.

## Step 8 — Branch and write

- Confirm a feature branch exists per the convention's naming. If still on `master`, create one first.
- Write or update `docs/interfaces/$1.md`.
- Commit on the branch.

## Step 8b — Report review findings (out-of-band)

After the doc is written and committed, present the collected review findings as a separate message — not in the doc, not in the commit. Format: short bullets, each `<job name> — <finding> — <severity: perf | bug | smell>`. For APIs, weight perf findings higher. If nothing notable came up, say so — don't pad. the user decides if anything becomes a separate fix branch or KEDB entry.

## Step 9 — Push prompt

Ask the user whether to push the branch.

Do **not** push without explicit confirmation. Do **not** create the PR — the user does that in Azure DevOps.
