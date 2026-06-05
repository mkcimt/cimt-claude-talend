# Knowledge Library — Index

Markdown reference material loaded on demand by skills, agents, and project `CLAUDE.md` pointers. Organized by topic.

## `mechanics/` — Layer 2a: Universal Talend truth

How Talend Studio and its artifacts actually work. No project-level choice involved.

- [`item-file-format.md`](mechanics/item-file-format.md) — Reading `.item` files, tMap XML caveats, picking the right version, citation conventions.
- [`item-properties-touch.md`](mechanics/item-properties-touch.md) — Why `.properties` siblings must be touched on `.item` edits (TMC `repository.commit.id` tracking).
- [`item-editing-programmatic.md`](mechanics/item-editing-programmatic.md) — Hard rules and pre-edit checklist for editing `.item` files from outside Studio: CRLF line endings, `<elementParameter>`-internal id uniqueness, UTF-8 (no BOM), embedded-entity preservation.
- [`joblet-inlining.md`](mechanics/joblet-inlining.md) — Joblets are inlined templates, not function calls. Sizing formula for generated `.java`, JDT formatter OOM threshold, Joblet → Job refactoring trade-off.
- [`studio-clean-and-codegen.md`](mechanics/studio-clean-and-codegen.md) — Studio has no Project → Clean menu. Forcing a regenerate by hand. Diagnosing `processCode is null` (always a downstream symptom — read `.metadata/.log` for the real cause).
- [`studio-noise-filter.md`](mechanics/studio-noise-filter.md) — Diff noise patterns Studio writes on save; what to ignore vs. what to review.
- [`git-workflow.md`](mechanics/git-workflow.md) — Feature branch discipline, worktrees alongside Studio, push protocol.
- [`operational-vs-documentation.md`](mechanics/operational-vs-documentation.md) — Read-live principle: build/deploy/promote/review must read live state; documentation may cache with explicit staleness markers.
- [`scratch-files.md`](mechanics/scratch-files.md) — Where Claude's temporary working files go: `.claude/tmp/` (gitignored, invisible to Studio's Git Staging).

## `patterns/` — Layer 2b: Optional patterns

Patterns a Talend project may or may not use. The variant in use is **detected from the project's artifacts** at the moment it becomes relevant — each pattern file documents the detection cues. No pre-declaration in `CLAUDE.md` is needed.

- [`context-variables.md`](patterns/context-variables.md) — Built-in context groups vs. external framework repo vs. `tContextLoad`. Detection cues and how to look up `context.getProperty(...)` per variant.

*(Add `batch-job-framework.md` etc. here as the catalog grows — each with its own detection cues.)*

## `tmc/` — Talend Management Console (Cloud) API

TMC API surface and gotchas. Pure mechanic — applies to any project using TMC.

- [`task-management.md`](tmc/task-management.md) — Full Public API reference (Orchestration + Processing). Build / publish / bind / promote / deploy flows.
- [`versioning.md`](tmc/versioning.md) — The three independent version axes (Studio **job version**, published **artifact version**, server-side **task version**): who bumps each, when, and how they relate. Job version is compiled into the generated Java package; artifact version is `semver.buildTimestamp` per publish; task version is a server-side revision counter dropped on `PUT`.
- [`microservice-lifecycle.md`](tmc/microservice-lifecycle.md) — Lifecycle quick-ref for ESB data-service microservices.
- [`microservice-log-collection.md`](tmc/microservice-log-collection.md) — The Log-Server collector-pool saturation trap: default `ms.worker.thread.number` too small → blocking log4j2 `SocketAppender` freezes a microservice's whole request pool. Diagnosis via SIGQUIT, fix via the collector cfg + DSR restart (no re-deploy).
- [`deployment-modes.md`](tmc/deployment-modes.md) — Microservice on Remote Engine vs. OSGi bundle on Talend Runtime. The one project-level choice not derivable from artifacts — ask-once-and-persist.
- [`known-bugs.md`](tmc/known-bugs.md) — Empirically verified TMC bugs and the workarounds we apply.

## `tds/` — Talend Data Stewardship (Cloud) REST API

TDS REST API surface, verified live, and the CLI that drives it ([`tools/tds_ops.py`](../tools/tds_ops.py), [`tools/tds_client.py`](../tools/tds_client.py)).

- [`api-reference.md`](tds/api-reference.md) — Auth, services (schemaservice / data-stewardship / semanticservice), endpoints + payloads for data models, campaigns, and the semantic-type sandbox→draft→publish lifecycle, with citation URLs.
- [`known-gaps.md`](tds/known-gaps.md) — Docs-vs-live reconciliation: what has no REST API (tasks, DQ rules → UI / Studio components) and the live-verified delete reality (campaign delete via `/campaigns/owned/{name}`; model delete blocked while referenced), plus the clean-teardown order.
- [`demo-workflows.md`](tds/demo-workflows.md) — Stand up and tear down a TDS demo (data model + RESOLUTION campaign + semantic type) with `tds_ops.py`; writes are dry-run by default.

## `build-publish/` — Headless Talend build & TMC publish

Local Maven build and TMC Cloud Publisher mechanics.

- [`release-runbook.md`](build-publish/release-runbook.md) — End-to-end recipe: build → publish → bind → promote → deploy.
- [`maven-build.md`](build-publish/maven-build.md) — Maven internals, deprecated parameters, headless CommandLine bootstrap.

## `code-review/` — Review principles and Talend heuristics

What the `talend-code-reviewer` agent applies.

- [`principles.md`](code-review/principles.md) — Five general principles + Talend-specific heuristics by component type (tMap, SQL, schemas, etc.).

## `documentation/` — Interface documentation convention

Templates and rules for per-interface docs.

- [`conventions.md`](documentation/conventions.md) — Batch vs. API templates, upfront-question sets, §5-from-tMap-output rule, review-findings handling, model-selection heuristics.

## How to reference these files

From a skill or agent: prefer absolute paths via the `CIMT_TALEND_PATTERNS` env var, e.g. `$CIMT_TALEND_PATTERNS/knowledge/tmc/task-management.md`.

From a project's `CLAUDE.md`: reference by canonical path (`knowledge/...`) and rely on the project's setup to make the directory discoverable.

## Adding new knowledge

See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the capture flow. Layer classification is non-negotiable — Layer 2a (truth) vs. Layer 2b (option) vs. Layer 3 (project) vs. Layer 4 (laptop). Each new file declares its layer in a short header line.
