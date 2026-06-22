# Backlog

Ideas and improvements for cimt-claude-talend. Not roadmap, not deadlines — just "we'd want this eventually".

Add new items at the top of the relevant section. When an item ships, move it under "Done" with a one-line summary and the date.

---

## Tooling

### project-intake — tighten interface clustering
Validated against a real project, the proposed-interface clustering still over- and under-merges: the utility-fanout caps (how widely a shared joblet/connection is allowed to pull artifacts into one cluster) are heuristic and don't always land on the right boundary. This is expected — clustering is an inference, and **TMC plans (phase 3) are the authoritative grouping** of which jobs actually run together. Treat this as "good enough to scope from, confirm against plans/manual", and revisit the caps once phase-3 plan data is available to compare against.

### project-intake — consolidate distinct-but-unresolved same-technology systems
Many endpoints are context-variable-driven (e.g. several DB connections whose host/db come from `context.*`), so they stay `resolved: false` and currently surface as **separate** systems because their locator strings differ. Consider consolidating distinct-but-unresolved endpoints of the same `(family, technology)` into a single placeholder system (or grouping them under one "resolve me" gap), so a real project with many context-driven endpoints of the same technology doesn't read as dozens of distinct systems. Needs care not to wrongly merge endpoints that really are different.

### project-intake phase 3 — TMC enrichment
Fill the canonical JSON's reserved `tmc{}` block from the Talend Management Console: environments, engines/infrastructure (Remote/Dynamic engines), the task → deployed-artifact mapping, plans (which jobs run together), and execution stats to derive cadence (how often each artifact actually runs). The phase-1 analyzer already emits the `tmc{}` block empty with `tmc` provenance reserved; this populates it via the TMC API alongside the static facts.

### project-intake phase 4 — manual capture
Capture the things no artifact or API can tell us: non-Talend flows in the same integration landscape, infrastructure not visible to TMC, and a gap round-trip where the analyst confirms/corrects the auto-derived inventory. Lands under the reserved `manual{}` block with `manual` provenance, so static / TMC / manual facts stay distinguishable.

### Calibrate the project-intake complexity metric
`tools/talend_complexity.py` currently emits an *uncalibrated* deterministic score (`calibrated:false`, ratings shown as `"estimated"`). Calibrate the weights against a real project plus a real Talend **Audit** export (Audit gives an independent complexity reference per job), then flip the flag and drop the "estimated" qualifier once the metric tracks reality.

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

(nothing here yet — this section gets the migration items as they land)
