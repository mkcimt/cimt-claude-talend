# Backlog

Ideas and improvements for cimt-claude-talend. Not roadmap, not deadlines — just "we'd want this eventually".

Add new items at the top of the relevant section. When an item ships, move it under "Done" with a one-line summary and the date.

---

## Tooling

### project-intake findings — refine `sql_dynamic` to value-injection only
The `sql_dynamic` smell currently fires on any query containing `+context.` or `globalMap` (`tools/talend_findings.py`). It over-fires on context-*parametrised* SQL — the common, perfectly fine pattern of injecting a schema/table/limit from a context variable. Make it informational, or refine the matcher to flag only **value injection into a WHERE/VALUES clause** (the actual injection/maintainability surface) rather than any context reference.

### project-intake findings — expand the catalog
The deterministic catalog is intentionally small and high-precision. Add more reliably-detectable patterns as they prove out: cartesian/unconstrained lookups (tMap join with no key), N+1 patterns (per-row DB calls inside a row-driven flow), and schema mismatches (column count/type drift across a connection). Keep precision-over-recall — only land a pattern once it's trustworthy from the XML alone.

### project-intake findings — tune the A+ deep-review triage thresholds
The two-tier handoff routes high-complexity artifacts to the `talend-code-reviewer` depth pass. The thresholds that decide *which* artifacts cross from breadth (deterministic findings) to depth (semantic review) are heuristic — tune them on real projects so the depth pass fires on the artifacts that actually warrant it, not too eagerly and not too rarely.

### project-intake findings — feed TMC-orphaned artifacts in as dead-code (optional)
Phase-3 TMC enrichment already marks artifacts deployed / worker-only / orphaned. Optionally surface TMC-orphaned artifacts (present on disk, never deployed/bound) into the findings dimension as a project-level `dead_code` signal, so the review rollup reflects artifacts that are dead at the *deployment* level, not just inactive components within a job. Read-only; depends on `--tmc`.

### project-intake — tighten interface clustering
Validated against a real project, the proposed-interface clustering still over- and under-merges: the utility-fanout caps (how widely a shared joblet/connection is allowed to pull artifacts into one cluster) are heuristic and don't always land on the right boundary. This is expected — clustering is an inference, and **TMC plans (phase 3) are the authoritative grouping** of which jobs actually run together. Treat this as "good enough to scope from, confirm against plans/manual", and revisit the caps once phase-3 plan data is available to compare against.

### project-intake — consolidate distinct-but-unresolved same-technology systems
Many endpoints are context-variable-driven (e.g. several DB connections whose host/db come from `context.*`), so they stay `resolved: false` and currently surface as **separate** systems because their locator strings differ. Consider consolidating distinct-but-unresolved endpoints of the same `(family, technology)` into a single placeholder system (or grouping them under one "resolve me" gap), so a real project with many context-driven endpoints of the same technology doesn't read as dozens of distinct systems. Needs care not to wrongly merge endpoints that really are different.

### project-intake phase 3 — refine plan chart→task membership
Phase-3 read-only enrichment lands the plans, but the chart→task membership read is still thin (plan flows carry little detail). Deepen the read so a plan's actual task set — which jobs run together — is captured reliably, since plans are the authoritative grouping for interface clustering (see "tighten interface clustering" above).

### project-intake phase 3 — confirm execution-stats fields
Confirm the execution-stats duration/status fields against real completed runs before relying on them to derive cadence — the field names/shapes should be validated on a project with execution history rather than assumed.

### project-intake — capture extension-less tLibraryLoad LIBRARY values
The dependency/upgrade-risk extraction reads `tLibraryLoad` LIBRARY values, but some are module names without a `.jar` extension and are currently missed. Broaden the matcher to capture those too.

### project-intake — artifactId-based task↔artifact matching
Phase-3 task↔artifact correlation is name-based, which misses tasks that were renamed or carry a REST display name distinct from the artifact. Add artifactId-based matching as the primary key, with name-matching as fallback.

### Calibrate the project-intake complexity metric
`tools/talend_complexity.py` currently emits an *uncalibrated* deterministic score (`calibrated:false`, ratings shown as `"estimated"`). Calibrate the weights against a real project plus a real Talend **Audit** export (Audit gives an independent complexity reference per job), then flip the flag and drop the "estimated" qualifier once the metric tracks reality. Also add logic-density proxies (beyond component/connection counts) and calibrate their weights, and tune the LLM complexity-review rubric (the triage hook from phase 3) against real projects.

### project-intake phase 4 — manual capture
Capture the things no artifact or API can tell us: non-Talend flows in the same integration landscape, infrastructure not visible to TMC, and a gap round-trip where the analyst confirms/corrects the auto-derived inventory. Lands under the reserved `manual{}` block with `manual` provenance, so static / TMC / manual facts stay distinguishable.

### Auto-derive `talend.p2.update.url` from `talend.project`
Read `productVersion` (e.g. `8.0.1.20260102_0846-patch`) from the project's `talend.project` file, map the date to the matching Talend monthly-update site (`R2025-12` etc.), set `talend.p2.update.url` if unset. Cuts one manual setup step. The mapping table from build date to R-tag isn't in the file itself — needs Qlik's release cadence; check whether the bundled CommandLine exposes this anywhere.

### OS keychain for `tmc.pat`
Replace the plaintext PAT in `talend.local.properties` with an OS keychain entry (macOS Keychain, Linux libsecret, Windows Credential Manager — via the `keyring` Python package). UX for the user is unchanged: `setup/store_pat.py` prompts and stores; tools that need the PAT retrieve transparently. The `.local.properties` file just keeps a `tmc.pat=<keychain>` marker.

### `cmd_deploy` health-check
After `POST /processing/executions`, snapshot execution IDs on the task pre- and post-deploy, then poll for a new `executing` entry (typically within 5–15 s). Currently returns the deploy receipt and the user is left wondering whether it actually deployed. See `knowledge/tmc/known-bugs.md` for the underlying behaviour.

### Multi-API release driver
`tmc_release.py release <api>` runs one artifact end-to-end. Add a multi-API variant that takes a list and runs them with a configurable fail strategy (fail-fast vs. continue-on-error), Maven multi-module reactor for the build phase, sequential publish.

---

## Skills + agents

### `document-interface`: cross-interface joblet awareness
Before deep-reading a joblet during `/document-interface`, check whether that joblet is also referenced by other interfaces in the project (`grep` for the joblet name across `process/` and `routes/`). If yes, the skill should either link to an existing shared description (if the project maintains `docs/joblets/`) or surface to the user that the joblet is shared, so it doesn't get re-described in two place with potentially divergent content. Applies to documentation only — code review and operational commands must always read live.

### `review-talend-branch`: pass only the changed code section to the code-reviewer
Currently the branch-reviewer passes full changed files to the code-reviewer. For topology / connection / tRunJob checks, the diff alone would suffice and save tokens. Caveat: Principle 1 (Exhaustiveness) needs more than the diff — the agent must derive the universe from the schema. The handoff would need to be **targeted**: diff for topological checks, broader context for guard/schema checks. Decide on a heuristic for "which checks need full file vs. diff".

### Model selection telemetry
Both review agents currently run on Opus. File count is not a reliable complexity proxy — many small file changes can be cheap, one huge refactor in one file is expensive. Watch token usage over the next several real runs and decide whether the branch-reviewer can drop to Sonnet (code-reviewer stays on Opus).

---

## Knowledge base

### Validate project-intake ESB route/service detection (still open)
The DI + REST-data-services validation pass confirmed the DI/REST `.properties` `xsi:type` tokens, the non-XMI item bodies, the `tRunJob` target id format, and project-root nesting (folded into `knowledge/mechanics/artifact-detection.md`). **Still unvalidated:** the ESB route/routelet/service `xsi:type` strings (`RouteItem`, `RouteProcessItem`, `CamelProcessItem`, `RouteletItem`, `ServiceItem`) and the on-disk route layout / `cTalendJob`-target + routelet-reference call mechanics — the validation project had no ESB. The dominant-`c*` prefix histogram remains the robust fallback. Validate against the first real ESB project and replace the remaining `[VALIDATE]` markers with confirmed values.

### Harden project-intake `elementParameter` key names against more real projects
Vendor component prefixes are robust, but the `elementParameter` connection-key names the component catalog reads to resolve a generic component's target system (`tDB*`, `tJDBC*`, `tMom*`, `cMessagingEndpoint` identity/object params) are still convention-based. Confirm and extend the synonym lists as more real projects (with different vendors) are analysed.

### Inventory pattern doc
Some projects need an inventory of shared joblets / cross-cutting routines so they can be documented once and referenced from multiple interface docs. Write a Layer-2b knowledge note describing the convention: where the inventory lives in the consuming project (`docs/joblets/<name>.md`), the format (purpose + which interfaces use it), and how `/document-interface` interacts with it.

### Pattern file: batch job frameworks
Empty placeholder right now. Document the Job Instance Framework (custom components from the upstream repo) plus the "bespoke per-project dispatcher/worker" pattern, with detection cues.

---

## Done

- **project-intake — deterministic static-review findings dimension** (2026-06) — `tools/talend_findings.py` adds a high-precision breadth review pass per `.item` (reload-lookup + SQL perf/smell, inactive/dead code, missing error handling), with a two-tier triage handing depth-pass artifacts to the `talend-code-reviewer`. Offline tests in `tests/test_talend_findings.py`.
- **project-intake phase 3 — read-only TMC enrichment** (2026-06) — `tmc{}` block populated from TMC (environments, engines, workspaces, tasks, plans) and correlated with the static inventory into deployed / worker-only / orphaned with per-env + prod-presence facts. Read-only by construction; validated live. `tools/tmc_client.py`, `tools/tmc_intake.py`, `knowledge/tmc/intake-read-only.md`.
- **project-intake — dependency/upgrade-risk dimension** (2026-06) — `tools/talend_dependencies.py` extracts jars/libs per artifact and detects version drift across the project, surfacing upgrade risk. Read-only; validated live.
