# Project Intake — Offline Talend Project Analysis

**Layer 2b (optional pattern).** The method behind the `/project-intake` skill: an offline analyzer that turns a Talend Studio project on disk into a single canonical JSON inventory, then renders it to Excel. Used to scope **upgrade, monitoring, and review estimation** before a single line of code is touched. A project may or may not use this — it is a way of *looking at* a project, not a pattern baked into one.

The companion mechanics docs explain the two engines this method drives: how components are mapped to external systems ([`component-system-catalog.md`](../mechanics/component-system-catalog.md)) and how artifacts are discovered and typed without trusting names ([`artifact-detection.md`](../mechanics/artifact-detection.md)). The on-disk format both rest on is [`item-file-format.md`](../mechanics/item-file-format.md).

## Why offline, name-independent

Real projects arrive with no naming convention you can trust and often no TMC access on day one. So the analyzer never reads the job/route *name* to decide what it does — it reads the **components** a job is built from. `tOracleInput` reads Oracle no matter what the job is called. The whole inventory is derivable from a plain Git checkout: stdlib-only, no credentials, no running TMC, no Talend Audit licence.

## The four-phase model

The intake is a pipeline. Each phase only adds; nothing downstream rewrites what an earlier phase established.

1. **Static offline analyzer** — `tools/project_intake.py`. Walks the project tree, classifies every artifact, maps components to external systems, builds the call graph, proposes logical interfaces, scores complexity, and collects everything it could not resolve into `gaps[]`. Emits the canonical JSON. **This is the only phase that exists today.**
2. **Excel render** — `tools/intake_to_excel.py`. Pure rendering of the canonical JSON into a colour-coded `.xlsx` (one sheet per concern, a *Provenance* column on each). No analysis logic lives here, so the workbook and the JSON can never disagree. Requires `openpyxl`; the analyzer deliberately does not, so the JSON is always producible.
3. **TMC enrichment** *(not yet built)* — would log in to Talend Management Console and fill the reserved `environments[]`, `infrastructure{}`, and `tmc{}` structures: which environments exist, which engines run what, the **plans** (which jobs actually run together, and on what cadence), and execution statistics. Facts it adds carry `provenance: "tmc"`.
4. **Manual gap resolution** *(human/customer dialogue)* — work the `gaps[]` worklist and the `manual{}` overrides: real hostnames behind context-driven connections, what an unknown component talks to, confirming or renaming proposed interfaces, non-Talend flows that the code cannot reveal. Facts it adds carry `provenance: "manual"`.

## Provenance discipline

**Every fact carries `provenance ∈ {static, tmc, manual}`.** This is the backbone of the whole method: a reader (and a later phase) must always be able to tell what was derived from code versus what came from TMC versus what a human asserted. The static analyzer emits only `static` facts and reserves empty `tmc` / `manual` / `gaps` structures for the later phases to fill. The Excel renderer colour-codes every row by provenance (green = static, blue = tmc, amber = manual) so the distinction survives into the workbook.

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
- **`environments[]`** — reserved; populated by TMC enrichment (phase 3). Empty from static.
- **`infrastructure{}`** — `tmc_region`, `workspaces`, `engines`, `run_profiles`, `manual_notes`. Reserved for phases 3–4.
- **`systems[]`** — the deduped registry of distinct external endpoints. Each: `system_id` (stable hash of family/technology/locator), `family`, `technology`, `identity{}` (host/port/database/schema/uri/endpoint/bucket-queue-topic, each a value or `"(unresolved)"`), `objects[]`, `confidence`, `resolved`, `provenance`, and `evidence[]` (the artifact/node/component sightings that prove it).
- **`artifacts[]`** — one entry per physical artifact: `type`, `complexity{}` (see below), `systems_read` / `systems_write` / `systems_connection` (system_id lists), `calls[]` (`tRunJob`/`cTalendJob` edges, with resolved `target_artifact_id` or `"(unresolved)"`), `components[]` (per-node classification), `context_vars[]`, `repo_connection_ids`, `joblets_used`, `type_signals`, `non_standard_flags`, version info, and reserved `tmc_task` / `tmc_execution_stats` slots. `provenance: "static"`.
- **`interfaces[]`** — the proposed logical clusters (see above): `status: "proposed"`, `confidence`, `member_artifacts`, `entry_points`, `cluster_signals`, `ambiguous_members`, `systems_touched`, and a reserved `tmc_plan_ref`.
- **`tmc{}`** — `enriched: false` until phase 3 runs; reserves `tasks`, `plans`, `execution_stats`, `component_metrics`.
- **`gaps[]`** — the phase-4 worklist (see contract above).
- **`manual{}`** — `interface_renames`, `system_overrides`, `notes` — where phase-4 human decisions are recorded without mutating the static facts.

## Complexity is estimated and uncalibrated

The per-artifact complexity score is a deterministic, weighted, soft-capped sum of static signals (component count, tMap count and output expressions, lookups, sub-jobs, `tRunJob` depth, external-system count, SQL/code lines, loops, flow-control, context vars). Buckets reproduce Talend Audit's five classes (Very Simple … Very Complex) so the output is comparable *when* an Audit export exists.

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
