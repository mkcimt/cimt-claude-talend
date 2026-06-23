# Project Intake — Offline Talend Project Analysis

**Layer 2b (optional pattern).** The method behind the `/project-intake` skill: an offline analyzer that turns a Talend Studio project on disk into a single canonical JSON inventory, then renders it to Excel. Used to scope **upgrade, monitoring, and review estimation** before a single line of code is touched. A project may or may not use this — it is a way of *looking at* a project, not a pattern baked into one.

The companion mechanics docs explain the two engines this method drives: how components are mapped to external systems ([`component-system-catalog.md`](../mechanics/component-system-catalog.md)) and how artifacts are discovered and typed without trusting names ([`artifact-detection.md`](../mechanics/artifact-detection.md)). The on-disk format both rest on is [`item-file-format.md`](../mechanics/item-file-format.md).

## Why offline, name-independent

Real projects arrive with no naming convention you can trust and often no TMC access on day one. So the analyzer never reads the job/route *name* to decide what it does — it reads the **components** a job is built from. `tOracleInput` reads Oracle no matter what the job is called. The whole inventory is derivable from a plain Git checkout: stdlib-only, no credentials, no running TMC, no Talend Audit licence.

## The four-phase model

The intake is a pipeline. Each phase only adds; nothing downstream rewrites what an earlier phase established.

1. **Static offline analyzer** — `tools/project_intake.py`. Walks the project tree, classifies every artifact, maps components to external systems, builds the call graph, proposes logical interfaces, scores complexity (deterministic), extracts external-library dependencies, and collects everything it could not resolve into `gaps[]`. Emits the canonical JSON. Stdlib-only, no credentials, no network.
2. **Excel render** — `tools/intake_to_excel.py`. Pure rendering of the canonical JSON into a colour-coded `.xlsx` (one sheet per concern, a *Provenance* column on each). No analysis logic lives here, so the workbook and the JSON can never disagree. Requires `openpyxl`; the analyzer deliberately does not, so the JSON is always producible.
3. **TMC enrichment** *(implemented — strictly READ-ONLY)* — `tools/tmc_intake.py`, driven by `--tmc`. Reads Talend Management Console state through the read-only `tools/tmc_client.py` and fills the `environments[]`, `infrastructure{}`, and `tmc{}` structures: which environments exist, which engines run what, the workspaces, the tasks and plans, and — by correlating deployed tasks back to the static artifacts — which jobs are actually **deployed**, in **which environments** (prod is authoritative), which run only as **workers** under a deployed parent, and which are **orphaned** (dead-code candidates). With `--tmc-stats` it also pulls per-task execution statistics. Facts it adds carry `provenance: "tmc"`. **This phase never mutates TMC** — see "Read-only by construction" below.
4. **Manual gap resolution** *(human/customer dialogue)* — work the `gaps[]` worklist and the `manual{}` overrides: real hostnames behind context-driven connections, what an unknown component talks to, confirming or renaming proposed interfaces, non-Talend flows that the code cannot reveal. Facts it adds carry `provenance: "manual"`.

In addition, an **optional LLM semantic-complexity pass** runs on top of phase 1's deterministic score (see "Complexity is two-tier" below): for the artifacts the deterministic pass flags as `needs_llm_review`, Claude reads the `.item` and rates *semantic* complexity into `complexity.llm_rating`. This is skill-driven, not a separate tool — see [`skills/project-intake.md`](../../skills/project-intake.md).

## Provenance discipline

**Every fact carries `provenance ∈ {static, tmc, manual}`.** This is the backbone of the whole method: a reader (and a later phase) must always be able to tell what was derived from code versus what came from TMC versus what a human asserted. The static analyzer emits only `static` facts and reserves empty `tmc` / `manual` / `gaps` structures for the later phases to fill; the TMC enrichment adds only `tmc` facts; phase 4 adds only `manual` facts. The Excel renderer colour-codes every row by provenance (green = static, blue = tmc, amber = manual) so the distinction survives into the workbook.

## Phase 3 is READ-ONLY by construction

The TMC enrichment reads live console state but **must never change it** — you are looking at a customer's running production environment. The guarantee is enforced in code, not assumed:

- The only public verb on `tools/tmc_client.py` is `get()`. There is no post/put/patch/delete; no code path issues a mutating request.
- Every request funnels through a single choke point that **raises `TmcReadOnlyViolation` on any method other than GET** (belt-and-suspenders), and the module's self-test asserts that every `urllib` request it builds uses GET.
- Requests are restricted to a **defence-in-depth allow-list** of read API prefixes (orchestration, processing, observability, execution-history, monitoring, audit); a path outside it is refused *before any network I/O*.
- Every call is recorded in an **audit list** (`tmc.requests_made` in the JSON counts them), so an engagement can show exactly what was queried.

**Why the guarantee lives in code, not in the token:** a TMC Personal Access Token carries its owner's *full* permissions — TMC PATs are **not** read-scoped. A PAT minted by a user who can deploy and promote could, in principle, do so; nothing about the token restricts it. So the read-only property cannot come from the credential — it has to come from the client. For defence in depth, **provision the PAT from a TMC service account that holds only a read-only role**, so even a hypothetical bug in the client cannot escalate beyond reads. Config keys are `tmc.pat` and `tmc.region` (or `tmc.base_url`) in `.claude/talend.local.properties` (gitignored). See [`../tmc/intake-read-only.md`](../tmc/intake-read-only.md).

## Deployed vs worker vs orphaned — and per-environment presence

Phase 3 correlates the TMC **tasks** back to the static `artifacts[]` by name, then classifies every deployable artifact (job/route/service/spark/mr — joblets, routelets and routines are never standalone tasks):

- **deployed** — the artifact has its own TMC task in at least one environment. Its `tmc_task` block records `deployed_in_environments[]`, `in_prod` (true if any task lives in a prod-named environment), the task and workspace ids, whether it is paused in all environments, and the runtime type.
- **reachable_via_parent (worker)** — no task of its own, but reachable over the `tRunJob`/`cTalendJob` call graph from a deployed job. A job with no task is *not* automatically dead — it may be a sub-job a deployed parent calls.
- **orphaned_candidates** — deployable, but neither deployed nor reachable from anything deployed. These are dead-code candidates — confirm before acting.

**Per-environment presence is first-class.** The same job can have tasks in several environments; the summary's `deployment_by_environment{}` counts deployments per environment and `deployed_in_prod` counts the prod ones. **Treat prod as the authoritative "what actually runs" view** — non-prod environments are routinely stale (old jobs left bound in dev/tst that no longer run anywhere real). Correlation is name-based, so renamed tasks or REST services may not match; those land in `unmatched_tasks[]`.

## The dependency / upgrade-risk dimension

Static phase 1 also extracts every **external library / JAR / driver** referenced in the `.item` files (DB `DRIVER_JAR`, `tLibraryLoad` libraries, and bare `*.jar` literals in any parameter) into the top-level `dependencies{}` block. The single biggest predictor of **upgrade breakage** is hard-referenced external libraries — above all **version drift**: the *same* library pinned to *different* versions across the project (e.g. a DB driver referenced as both `<lib>-9.8.jar` and `<lib>_V6R1.jar`). The summary flags every drifting library in `version_drift[]`, the version-pinned jars in `version_pinned_jars[]`, and rolls human-readable `upgrade_risk_flags[]` for the report. Hard-coded/version-pinned library dependencies are a major cost driver for any version upgrade and should be priced into the estimate; they also feed a complexity signal (`n_external_libs`) and force `needs_llm_review`.

## Interface (logical, proposed) vs artifact (physical)

Keep these two ideas separate — they answer different questions.

- An **artifact** is a physical thing on disk: one job, route, routelet, joblet, service, bean, routine, connection, or context. It is a *fact* — it exists, it has a type, it reads/writes specific systems.
- An **interface** is a *logical cluster* of artifacts that together implement one integration. Because the projects we analyse have no reliable naming, grouping artifacts into an interface is an **inference, never a fact**. The analyzer builds it from structural signals — `tRunJob`/`cTalendJob` call edges (strongest), shared context groups, shared repository connections, shared domain joblets, and same folder subtree — and emits every cluster with `status: "proposed"`, a `confidence`, and `cluster_signals` showing why. A call edge's target is stored on disk as `PROJECT:_<emfRepositoryId>` (the called artifact's repository id, **not** its label); resolution strips the `PROJECT:` prefix and matches the bare id against the called `.properties`, then looks the label up only for display (confirmed against a real project — see [`artifact-detection.md`](../mechanics/artifact-detection.md)). Anything that could belong to two clusters is listed in `ambiguous_members` rather than force-merged. A human confirms or renames interfaces in phase 4; TMC plans (phase 3) are the strongest external corroboration of which jobs truly belong together.

## Graceful degradation contract

The analyzer must never crash on a messy project, and must be honest about what it could not work out:

- **Never fatal.** Unknown components, broken `.item` files, and missing `.properties` all degrade gracefully and are *reported*, not raised. Parse failures land in `project.parse_errors[]`; type conflicts land in `project.non_standard_flags` and per-artifact `non_standard_flags`.
- **`"(unresolved)"`** is the literal string for a fact that is known-to-exist but not knowable from static code — most commonly a connection whose host/endpoint comes from a context variable. Unresolved-but-distinct endpoints of the same `(family, technology)` honestly collapse to **one** system marked `resolved: false` (you cannot tell two unresolved Oracle hosts apart from code alone).
- **`gaps[]`** is the worklist that ties it together: every `"(unresolved)"`, every unknown component, every unresolved `tRunJob` target, every ambiguous cluster, and every artifact whose type could not be determined becomes a gap with a `kind`, a `ref`, a `description`, a ready-to-ask `suggested_question`, and an empty `resolution` for phase 4 to fill.

## The canonical JSON document

One document, `schema_version` `"1.0"`, is the single source of truth for all four phases. Top-level keys:

- **`schema_version`, `generated_at`, `generator`** — provenance of the document itself (tool, version, complexity `config_version`).
- **`project`** — `name` and `product_version` (best-effort from `talend.project`, often `"(unresolved)"` on a bare checkout), `scanned_path`, `artifact_counts` (per type), `non_standard_flags` (project-wide roll-up of type/folder/component disagreements), and `parse_errors[]`.
- **`environments[]`** — populated by TMC enrichment (phase 3): each `{id, name, description, max_cloud_containers, is_default, provenance:"tmc"}`. Empty from static alone.
- **`infrastructure{}`** — `tmc_region`, `workspaces[]`, `engines[]` (filled by phase 3), plus `run_profiles` and `manual_notes` (phase 4).
- **`systems[]`** — the deduped registry of distinct external endpoints. Each: `system_id` (stable hash of family/technology/locator), `family`, `technology`, `identity{}` (host/port/database/schema/uri/endpoint/bucket-queue-topic, each a value or `"(unresolved)"`), `objects[]`, `confidence`, `resolved`, `provenance`, and `evidence[]` (the artifact/node/component sightings that prove it).
- **`artifacts[]`** — one entry per physical artifact: `type`, `complexity{}` (see below), `systems_read` / `systems_write` / `systems_connection` (system_id lists), `calls[]` (`tRunJob`/`cTalendJob` edges, with resolved `target_artifact_id` or `"(unresolved)"`), `components[]` (per-node classification), `context_vars[]`, `repo_connection_ids`, `joblets_used`, `dependencies[]` (per-artifact external jar/lib references), `findings[]` (the deterministic breadth findings on this artifact — see "Findings / review"), `type_signals`, `non_standard_flags`, version info, and the `tmc_task` / `tmc_execution_stats` slots filled by phase 3. `provenance: "static"`.
- **`dependencies{}`** — top-level external-library roll-up (see "upgrade-risk" above): `distinct_jars`, `distinct_libs`, `total_refs`, `version_drift[]`, `version_pinned_jars[]`, `upgrade_risk_flags[]`. `provenance: "static"`.
- **`findings{}`** — top-level deterministic-review roll-up (see "Findings / review" above): `total`, `by_severity`, `by_category`, a `note`, `provenance: "static"`. The per-artifact findings live on `artifacts[].findings[]`.
- **`interfaces[]`** — the proposed logical clusters (see above): `status: "proposed"`, `confidence`, `member_artifacts`, `entry_points`, `cluster_signals`, `ambiguous_members`, `systems_touched`, and a reserved `tmc_plan_ref`.
- **`tmc{}`** — `enriched: false` until phase 3 runs; once enriched it holds `region`, `tasks[]`, `plans[]`, `execution_stats[]` (only with `--tmc-stats`), a `summary{}` (deployed / deployed_in_prod / deployment_by_environment / reachable_via_parent / orphaned_candidates / unmatched_tasks), and `requests_made` (the read-only audit count).
- **`gaps[]`** — the phase-4 worklist (see contract above).
- **`manual{}`** — `interface_renames`, `system_overrides`, `notes` — where phase-4 human decisions are recorded without mutating the static facts.

## Findings / review — two-tier (breadth triages, depth reviews)

The intake carries a **review dimension** that mirrors the complexity model: a cheap deterministic breadth pass over the whole project, and an optional LLM depth pass on the subset that warrants judgement. The two never duplicate each other — breadth *triages*, depth *reviews*.

### Tier 1 — deterministic breadth catalog (always runs)

`tools/talend_findings.py` runs over every parsed `.item` and emits high-precision, project-wide candidate issues. **Precision over recall:** only patterns reliably detectable from the XML land here, so the list stays trustworthy. This deterministic Tier-1 catalog emits severities `perf | smell | dead_code`; the `bug` severity is reserved for the Tier-2 depth pass (the `talend-code-reviewer`), where hard semantic bugs are decided. The categories:

- **`lookup_reload`** *(perf)* — a tMap has reload-at-each-row lookup(s); the lookup is re-read for every input row.
- **`sql_select_star`** *(smell)* — `SELECT *` in a query (binds to schema drift, fetches unused columns).
- **`sql_leading_wildcard`** *(perf)* — leading-wildcard `LIKE '%…'` (non-sargable, forces a scan).
- **`sql_dynamic`** *(smell)* — dynamically concatenated SQL (`+context.` / `globalMap`): maintainability and injection surface.
- **`inactive_components`** *(dead_code)* — inactive (disabled) components left in the job.
- **`no_error_handling`** *(smell)* — an executable that writes to an external system but has no `tDie` / `tWarn` / `tLogCatcher` and no reject flow; failures may pass silently.

Each finding is `{severity, category, detail, location, provenance:"static"}`. Findings land per-artifact in `artifacts[].findings[]` and roll up into the top-level `findings{}` block (`total`, `by_severity`, `by_category`, a `note`, `provenance:"static"`). The Excel renderer surfaces them on a **Findings** sheet.

**`sql_dynamic` is intentionally broad and tends to fire a lot.** Context-parametrised SQL is normal, idiomatic Talend — most projects drive every query off `context.*`. Treat this category as **informational / tunable**: it marks a maintainability/injection *surface* to be aware of, not a defect. Filter or down-weight it when it dominates the rollup.

**Hard semantic bugs are NOT decided in Tier 1.** Guard completeness, auth-bypass paths, exhaustiveness gaps, symmetry breaks — these need judgement and are out of scope for the deterministic catalog by design. They are the job of Tier 2.

### Tier 2 — A+ depth review (optional, opt-in)

For depth, the intake hands a **triaged subset** of artifacts to the existing `talend-code-reviewer` agent (the `/review-talend-code` skill) for a semantic pass — it is the established DEPTH reviewer (see [`code-review/principles.md`](../code-review/principles.md): exhaustiveness, symmetry, end-to-end coherence, guards-dominate-targets, dead-code-is-drift). **Do not duplicate it here** — the intake's only job is to *select* what is worth that reviewer's time.

The triage is: any artifact where `complexity.needs_llm_review` is `true` **OR** whose `artifacts[].findings` is non-empty. Breadth picked the candidates; depth confirms hard bugs and checks guard completeness on exactly those. Confirmed issues fold into the review narrative (and optionally back into the doc as `provenance:"manual"` notes). This pass is **opt-in** — a pure flag-only intake (Tier 1 breadth, no depth) is a complete, valid result; the depth pass is what makes a review A+. The procedure lives in [`skills/project-intake.md`](../../skills/project-intake.md).

## Complexity is two-tier — deterministic, then optional LLM

### Tier 1 — deterministic (always runs)

The per-artifact complexity score is a deterministic, weighted, soft-capped sum of static signals (component count, tMap count and output expressions, lookups, sub-jobs, `tRunJob` depth, external-system count, SQL/code lines, loops, flow-control, context vars, and hard-referenced external libs). Buckets reproduce Talend Audit's five classes (Very Simple … Very Complex) so the output is comparable *when* an Audit export exists.

### Tier 2 — optional LLM semantic pass (skill-driven)

The deterministic score **counts** things; it cannot tell *20 trivial passthrough columns* apart from *10 gnarly ones* with nested ternaries and cross-variable dependencies. So each `complexity{}` block carries a `needs_llm_review` flag set when the deterministic count is least trustworthy — a heavy bucket (Complex/Very Complex), many tMap output expressions (≥ 20), or any hard external-library dependency. For exactly those flagged artifacts, the `/project-intake` skill has Claude read the `.item` (tMap output expressions, custom `tJava` code, dependencies) and write a *semantic* rating into the reserved `complexity.llm_rating = {rating, rationale, risk_factors[]}` field. The deterministic numbers are never overwritten — the LLM rating sits alongside them. The rubric and procedure live in [`skills/project-intake.md`](../../skills/project-intake.md).

**Until that calibration happens the score is an estimate, not ground truth.** Every weight, cap, divisor, and bucket threshold lives in one config dict, so calibration against a real project plus a real Talend Audit export needs zero code changes — only a new `config_version`. Until then every `complexity` block carries `calibrated: false` and the JSON/Excel/console summaries label the histogram "estimated, uncalibrated". Treat the buckets as relative ordering (heavier jobs score strictly higher), not as a precise effort figure.

The default bucket thresholds were raised to a realistic **uncalibrated baseline** — Very Simple ≤ 15, Simple ≤ 40, Moderate ≤ 80, Complex ≤ 130, Very Complex above — after the original toy-sized defaults rated roughly 70% of a real project Complex-or-worse. The new baseline produces a believable spread on a real-world-sized project (most artifacts Simple/Moderate with a Complex tail); it is **still `calibrated: false`** (`config_version` `default-uncalibrated-v1`). Real calibration against a Talend Audit export remains future work.

## How to harden against the first real project

The analyzer was built to a spec, then hardened against a first real project (a DI + REST-data-services project; **no ESB routes** were present). The validation status of the original `[VALIDATE]` items:

**Now confirmed (DI + REST data services):**

- **`.properties` `xsi:type` for DI + REST** — `ProcessItem`→job, `JobletProcessItem`→joblet, `RoutineItem`→routine, `SQLPatternItem`→sql_pattern, `ContextItem`→context, every `*ConnectionItem`→connection, and `DataServiceRESTMetadataFileConnectionItem`→REST data-service. `Transform:*` and `ReferenceFileItem` are metadata-only (no `.item`) and correctly not scanned.
- **Non-XMI item bodies** — routine, bean, and sql_pattern `.item` files hold Java/SQL source, not XMI; the analyzer no longer XML-parses them (no more false parse errors).
- **`tRunJob` / `cTalendJob` target id format** — confirmed as `PROJECT:_<emfRepositoryId>`, resolved by id-stripping + `.properties` match.
- **Project-root nesting** — the project root (the folder holding `talend.project`) is usually nested under a project-name folder in the workspace; point the analyzer there. `.properties` `xsi:type` stays authoritative regardless of folder depth.
- **Catalog + complexity baseline** — extra internal components/prefixes folded in, project-joblet nodes recorded as internal sub-flow invocations, and the complexity bucket thresholds raised to a realistic uncalibrated baseline (see above).

**Still open (`[VALIDATE]`):**

- **Exact `.properties` `xsi:type` strings for ESB** — routes, routelets, services (`RouteItem`, `RouteProcessItem`, `CamelProcessItem`, `RouteletItem`, `ServiceItem`, …). Unconfirmed: the validation project had no ESB. The component-prefix histogram (dominant `c*` ⇒ route) remains the robust safety net.
- **`elementParameter` key names** for identity and objects — the host/port/database/uri and table/queue/topic parameter names the component catalog reads. Vendor components are robust; generic components (`tDB*`, `tJDBC*`, `tMom*`, `cMessagingEndpoint`) resolve technology from param values and are the most likely to need new synonyms.
- **Route layout** — the on-disk folder structure and call mechanics for ESB (`cTalendJob` targets, routelet references) so the call graph and interface clustering hold up on a real routes project, not just batch jobs.
- **Audit calibration** — the complexity score is still `calibrated: false`; a real Talend Audit export is needed to flip it.

When an ESB project (and ideally an Audit export) lands: run the analyzer, diff its output against the Audit export, fold the corrected weights/thresholds into a new `calibrated-*` config, and add any missing component prefixes, ESB `xsi:type` tokens, and parameter synonyms to the catalogs. After that the score flips to `calibrated: true` and the inventory becomes trustworthy ground truth rather than an estimate.

## See also

- [`component-system-catalog.md`](../mechanics/component-system-catalog.md) — how a `componentName` (+ params) maps to an external system, direction, and confidence.
- [`artifact-detection.md`](../mechanics/artifact-detection.md) — how artifacts are found, version-selected, and typed from `.properties` + folder + component histogram.
- [`item-file-format.md`](../mechanics/item-file-format.md) — the `.item` / `.properties` format both engines read, version-selection rule, and citation conventions.
