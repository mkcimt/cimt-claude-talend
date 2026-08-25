# Backlog

Ideas and improvements for cimt-claude-talend. Not roadmap, not deadlines — just "we'd want this eventually".

Add new items at the top of the relevant section. When an item ships, move it under "Done" with a one-line summary and the date.

---

## Tooling

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

### Inventory pattern doc
Some projects need an inventory of shared joblets / cross-cutting routines so they can be documented once and referenced from multiple interface docs. Write a Layer-2b knowledge note describing the convention: where the inventory lives in the consuming project (`docs/joblets/<name>.md`), the format (purpose + which interfaces use it), and how `/document-interface` interacts with it.

---

## Done

### Pattern file: batch job frameworks
Landed as two files instead of one: [`knowledge/patterns/job-instance-framework.md`](knowledge/patterns/job-instance-framework.md) (the `tJobInstanceStart` / `tJobInstanceEnd` components, the bookkeeping tables, the "since my last successful run" window, per-work-item pointers) and [`knowledge/patterns/scd-dispatcher-worker.md`](knowledge/patterns/scd-dispatcher-worker.md) (the caller-parametrized dispatcher/worker variant, alongside the existing meta-table-driven `dynamic-scd-framework.md`). Both carry detection cues, an audit checklist and a project overlay slot.
