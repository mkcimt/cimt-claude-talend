# Interface Documentation Convention

> How to author and refresh per-interface documentation under `<project>/docs/interfaces/`.
> Source of truth for both human authors and the `document-interface` slash command.

## Scope

Per-interface docs serve **two audiences in one file**:

- **Business view** — the *what* and *why*: purpose, matching logic, mappings, calculations, rejects.
- **Technical orientation** — for Talend developers landing on the interface for the first time (e.g. Managed Services colleagues): which jobs are deployed, who calls whom, where the core logic sits.

Goal: a reader gets a **fast overview** of the interface. Detailed component-level logic (full SQL, complete tMap mappings, every column) is **not duplicated** — it lives in the `.item` files and is read live when needed.

## Two interface flavours

The convention splits along two structurally different kinds of interface, each with its own template:

- **Batch interfaces** — TMC-scheduled Data Integration jobs, file-based. Use the **Batch template**.
- **APIs** — Talend Data Services microservices, deployed directly to a Remote Engine. Consumed as a backend by an upstream service, so **performance matters**. Use the **API template**.

The templates share Section 1 (Purpose) and the final "Where to look" table; everything in between differs.

## Upfront questions (before reading any `.item`)

Clarify with the user before starting. Question set depends on the flavour:

**Batch interface:**
1. **Deployed jobs** — Which jobs are actually deployed (whole plan or single job)? List the top-level deployed jobs by name.
2. **Triggering** — TMC schedule, file-trigger, called by another interface, on-demand?
3. **Known oddities** — Any business gotchas to keep in mind while reading the code?
4. **Mode (only if file exists)** — *update-diff* or full rewrite?

**API:**
1. **Mode (only if file exists)** — *update-diff* or full rewrite?
2. **Project-defined overrides** — if the project's `CLAUDE.md` declares "do not ask about scope / callers / known oddities" (typical when there is a single known caller, all endpoints are in scope, oddities should be derived from code), skip those. Otherwise ask: scope, callers, known oddities.

The internal call chain (which job calls which joblet/routine) is **not** asked — derive it from `tRunJob` references and routine usage in the `.item` files.

## Batch template

```
# iXXX — <Title>

> Scope: business + technical orientation. Detailed logic lives in the `.item` files in <project>/process/iXXX_*.

## 1. Purpose
3–5 sentences, business framing. Both audiences read this.

## 2. Technical Overview
- Deployed jobs (TMC plan or single job) + how they're triggered — refer to jobs by **name only**
- Call chain: top-level → dispatcher → worker, plus tRunJob branches
- Where the core business logic lives (pointer to the worker job by name)
- Staging / reject / history tables in play (names + role, one line each)
- Mapping tables / context variables critical for understanding (only those — no full dump)

## 3. Basic Principle
Core mechanism in plain language.

## 4. Matching Logic
How incoming data is matched to existing records, validations, fallbacks.

## 5. Data Changes in Detail
Subsections — derive from the worker job's tMap output expressions (see "Deriving §5 from tMap output" below). Drop a section only if you have actively confirmed it does not apply.
- Field normalisations (uppercase, type casts, flag → bool)
- Field-name translations (source → target)
- Status / code mappings — name the mapping table **and** the `object_type` key, plus fallback behaviour
- Calculations — see "Worked example rule" below
- Enrichment from master data — use two columns, *Source on Update* and *Source on New Line*, even when identical; this forces the asymmetry check
- Fixed-value fields (literals like `null`, `false`, `""` in tMap output)
- Retained-on-update fields (tMap output expression references the existing target row, not the incoming row)

## 6. Historisation
What is historised, when (before update / before delete), into which table. Skip if not applicable.

## 7. Rejected Records
Reject reasons, target table, downstream handling. **Add a Path/Flow column** when the job has multiple processing paths so the reader sees in which flow each reject originates. Skip if not applicable.

## 8. Where to look
Citation table: job name → relative `.item` path inkl. version (highest = active).
```

Sections 4–7 are a template — adjust to the interface. Drop sections that don't apply rather than padding ("None" placeholders are noise).

## Deriving §5 from tMap output expressions

§5 subsections come from the worker job's tMap output table. Walk the output expressions once and bucket by pattern:

| Pattern in tMap output expression | Goes into |
|---|---|
| Literal `null`, `false`, `""`, fixed string/number | Fixed-value fields |
| `row1.field` / `existingRow.field` (reference to existing target row lookup, not incoming row) | Retained-on-update fields |
| Conditional `inputRow.field == null ? row1.field : inputRow.field` | Retained-on-update *with* documented condition |
| `StringHandling.UPCASE(...)`, `TalendDate.parseDate(...)`, `"1".equals(...)`, casts | Field normalisations |
| Source column name ≠ target column name (otherwise straight passthrough) | Field-name translations |
| Ternary on a mapping-table lookup with fallback to the raw value | Status/code mappings (with fallback note) |
| Lookup row reference (`partMaster.field`, `customerMaster.field`) | Enrichment from master data |
| Different expression in the "new" output table vs. the "update" output table for the same column | Enrichment / Retained-on-update — **always document both columns** |

Rule of thumb: every output column lands in exactly one of the §5 subsections. If it doesn't, you have either missed it or the section is genuinely empty (rare).

## Worked example rule

Add a concrete numeric example (with named inputs and the resulting output value) for any calculation that:

- combines more than two input fields, **or**
- has more than one branch in the formula, **or**
- aggregates over a repeating group.

A single short paragraph with realistic numbers beats half a page of prose. Skip the example for trivial 1:1 transforms.

## Resolving `context.getProperty("...")`

See [`../patterns/context-variables.md`](../patterns/context-variables.md) — detect the project's pattern variant from its artifacts, then locate the right framework root and properties file accordingly.

Do **not** embed full property values in the doc unless the value *is* the business rule (e.g. a status enum). For connection details, just point at the framework key by name.

## API template

```
# iXXX — <API Title>

> Scope: business + technical orientation for a Talend Data Services microservice.

## 1. Purpose
3–5 sentences. What domain object does this API expose? Who calls it, and why?

## 2. API Definition
- Path to the Swagger/OpenAPI artifact
- Auth mechanism (token validation, role check entry point)
- **Endpoints table** — sourced from the API definition, then verified against the implementation:

| Method | Path | Query/Path Params | Handler Job | Notes |
|---|---|---|---|---|

Endpoints + query/path params should match the Swagger; if not, list the mismatch in §6 (Drift). Request/response object schemas are *not* documented here.

## 3. Endpoint Behaviour
Per endpoint (or grouped where logic is shared): what it does in business terms, which worker job runs it, callers if known.

**Rejection cases are mandatory for every mutation endpoint** (POST / PUT / PATCH / DELETE) and for any GET with non-trivial auth or filtering. Cover at minimum:

- Permission gates (global API permission, admin-only endpoints, customer-level access)
- State preconditions (record must be in status X, must not be already sent, etc.)
- Input validity (mandatory fields, "at least one of …" rules, conflicting field combinations)
- Existence checks (referenced parent / lookup record must exist)

A rejection rule that lives only in code and not in the doc will surprise callers in production.

## 4. Internal Query Composition
Document **how the SELECT (or update) is actually built**, beyond user-supplied query params:
- **Authorization filtering** — which user/role check, which rows it eliminates
- **Row filtering** — implicit filters (tenant, status, soft-delete flags, date windows)
- **Column filtering** — which columns are not shown, how that's enforced
- **Shared vs. bespoke** — flag which parts come from common helpers (QueryParser / Util / AuthManager / similar) and which are hand-rolled
- A representative resulting SELECT shape (pseudo-SQL is fine).

## 5. Shared Helpers in Use
Routines, joblets, routelets that this API relies on for cross-cutting concerns. One line each: name + role.

## 6. Known Drift / Open Issues
Where the API definition (Swagger) and the implementation disagree. Short bullets, factual, no recommendations.

## 7. Where to look
Citation table: endpoint / job name → relative `.item` path inkl. version. Plus path to the Swagger JSON.
```

Sections 4 and 5 are the heart of an API doc — that is what readers come for.

## Update-diff mode

When a doc already exists and the underlying jobs have changed:

1. Read the existing doc.
2. Re-read the deployed `.item` files (anchored on the upfront-question answers).
3. Diff content vs. doc — focus on "subject to change" areas: field mappings, SQL joins/filters, mapping tables, reject reasons, historisation rules (batch); endpoint set + query params, filter logic in §4, helper usage in §5, drift in §6 (API).
4. Propose changes inline *before* writing.
5. Stable sections (Purpose, Basic Principle) usually do not change — don't rewrite for cosmetics.

## Job names vs. file paths

In document body and chat: refer to a job by its **job name** (no `_0.1.item` suffix). The Talend-internal version is metadata noise for the reader.

The exact path inkl. version is a **citation** so the user can verify the right file was picked. Place citations in the final "Where to look" table — not inline in prose. Highest version number = active.

## Review findings (out-of-band)

While reading `.item` files for documentation, you will sometimes spot real issues — N+1 patterns, missing indexes, dead code, suspicious joins, auth gaps, sloppy reject handling. **These do not go into the doc** (the doc describes, it doesn't review).

Instead, collect a short review-findings list in the background and present it *after* the doc draft is agreed. Format: `<job> — <finding> — <severity: perf | bug | smell>`. For APIs, weight perf findings higher.

**Exception — functional gaps that affect the API contract belong in the doc.** If a guard expression is incomplete, an auth check is bypassable, or a documented enum value is silently dropped, and the gap directly changes how a caller experiences the API, surface it in §6 (Known Drift / Open Issues). Rule of thumb: would a caller reading the doc be misled if the issue weren't mentioned? If yes → §6. Otherwise → out-of-band review list.

## Pre-doc completeness pass (new API doc only)

For **new** API docs (not update-diff), before drafting §3 / §4, run an explicit completeness pass on the deployed joblets. Goal: catch the class of bugs where a guard expression looks right but quietly omits a field. Applied checks mirror the `talend-code-reviewer` agent's "Guard / Validation Completeness" section — see [`../code-review/principles.md`](../code-review/principles.md).

Findings route per the rule above: contract-affecting gaps → §6; other findings → out-of-band review list. The pass is skipped for update-diff mode.

## Model selection

| Scenario | Model |
|---|---|
| Single deployed job, linear logic, ≤3 jobs in chain | Sonnet (latest) |
| New doc for complex batch interface (>3 deployed jobs, branched topology, deeply nested tMaps with multiple lookups) | Opus (latest) |
| New API doc with many endpoints or non-trivial filter composition | Opus (latest) |
| Small API (≤3 endpoints, mostly shared-helper usage) | Sonnet |
| Update-diff mode | Sonnet (escalate if diff is large or unclear) |
| User signals "this is one of the big ones" | Opus |

Default is Sonnet. Escalate when complexity is **visible from the upfront-question answers**, not after struggling. Specific thresholds (e.g. ">3 jobs") may need project-specific tuning — see the project's `CLAUDE.md`.

## Git workflow

Always create a feature branch first — see [`../mechanics/git-workflow.md`](../mechanics/git-workflow.md). Recommended branch name: `docs/iXXX-doc`.

After commit, ask the user before pushing.
