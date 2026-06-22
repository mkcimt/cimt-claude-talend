# Artifact Detection (Without Trusting Names)

A Talend project tree is full of `.item` files with no reliable naming convention: a "job" might live anywhere, be named anything, and coexist with archived and superseded copies. This module discovers every artifact and decides **what each one is** — job, route, joblet, service, connection, context, routine, … — using on-disk evidence, never the file name.

Source of truth: [`tools/talend_discovery.py`](../../tools/talend_discovery.py). It builds on the parser in [`tools/talend_item.py`](../../tools/talend_item.py) and, like it, **never raises** — it degrades and records flags instead.

## What `scan_project()` does

1. **Find & pair** — `rglob("*.item")` and pair each with its sibling `.properties`. A missing `.properties` is tolerated (`properties_path = None`).
2. **Exclude noise** — skip anything matched by `is_excluded()`: `*.lock` files, and any path segment that is an archive/retired marker — `a__archive/` (the canonical case) plus `archive`/`archived`/`obsolete`/`old`/`_old` segments and `*__archive` suffixes. Studio's `recycle_bin/` and `temp/` segments are excluded the same way.
3. **Version-select** — `<stem>_<major>.<minor>.item` (e.g. `<job_name>_0.1.item`, `<job_name>_0.2.item`) are **Studio-internal versions, not git versions** (see [`item-file-format.md`](item-file-format.md)). Group by `(folder, stem)`, sort, **highest `major.minor` wins**; the rest are recorded in `superseded_versions` and not analysed. A file with no version suffix sorts as `(-1, -1)`.

The result is one `ArtifactRef` per active artifact. `classify_artifact()` then fills in its type.

## Three-vote precedence

Type is decided by three independent signals, in strict precedence order — `type_from_props or type_from_folder or type_from_item or "unknown"`:

1. **`.properties` item element (authoritative).** The `.properties` XMI pairs a `<Property>` (label/id/version/purpose) with an item element whose local-name or `xsi:type` encodes the type (`ProcessItem`, `RouteItem`, …). `_canon_token()` strips any namespace prefix (`TalendProcess:ProcessItem` / `{ns}ProcessItem` → `ProcessItem`) before lookup in the type map. A token ending in `ConnectionItem` (e.g. `DatabaseConnectionItem`) maps to `connection`.
2. **Parent folder** (corroboration / fallback). Top-level folder name → type via `_FOLDER_TYPE` (`process/`→job, `routes/`→route, `joblets/`→joblet, …).
3. **`.item` component-prefix histogram** (robust fallback, requires the parsed `.item`). From `ItemModel.component_prefix_histogram()`: count leading letters of every `componentName`. **All `t*` ⇒ job**; **a dominant `c*` (more `c` than `t`, and `c > 0`) ⇒ route** — because routes are built from Camel `c*` components and jobs from `t*` components. This is the signal that survives even when `.properties` and folders are missing or wrong.

The component classification from [`component-system-catalog.md`](component-system-catalog.md) is the same `c*`-vs-`t*` distinction at the artifact level.

## Type map

`.properties` item element (after namespace-stripping) → canonical type, from `_TYPE_MAP`:

| Item element | Type |
|---|---|
| `ProcessItem` | `job` |
| `JobletProcessItem`, `JobletItem` | `joblet` |
| `RouteItem`, `RouteProcessItem`, `CamelProcessItem` | `route` |
| `RouteletItem`, `RouteletProcessItem` | `routelet` |
| `ServiceItem` | `service` |
| `SparkProcessItem` / `SparkStreamingProcessItem` | `spark_job` / `spark_streaming_job` |
| `MapReduceProcessItem`, `StormProcessItem`, `BigDataProcessItem` | `mr_job`, `storm_job`, `spark_job` |
| `ContextItem` | `context` |
| `RoutineItem` | `routine` |
| `BeanItem` | `bean` |
| `SQLPatternItem` | `sql_pattern` |
| `*ConnectionItem` (suffix rule) | `connection` |
| `DataServiceRESTMetadataFileConnectionItem` | `service` (REST data-service contract) |

The `DataServiceREST…` case is handled before the `*ConnectionItem` suffix rule: a token containing `DataServiceREST` is the **API contract of a REST data service**, so it classifies as `service` even though its element name also ends in `ConnectionItem`.

`EXECUTABLE_TYPES` (the "interface candidates") = job, route, routelet, joblet, service, and the big-data job variants.

**Confirmed against a real project.** Validated against a real DI + REST-data-services project, the `.properties` item `xsi:type` tokens above resolve as mapped: `ProcessItem`→job, `JobletProcessItem`→joblet, `RoutineItem`→routine, `SQLPatternItem`→sql_pattern, `ContextItem`→context; `DatabaseConnectionItem` / `GenericSchemaConnectionItem` / `ExcelFileConnectionItem` / `GenericConnectionItem` all hit the `*ConnectionItem` suffix rule → connection; and `DataServiceRESTMetadataFileConnectionItem` → REST data-service. Some element kinds — `Transform:StructuresItem` / `Transform:MapsItem` / `Transform:NamespaceItem`, and `ReferenceFileItem` — exist as **metadata only** (a `.properties` with no `.item`); they are correctly not scanned. ESB route/routelet/service tokens remain `[VALIDATE]` (see below).

## Non-XMI `.item` files: routine, bean, sql_pattern

**Confirmed:** the `.item` of a `routine`, `bean`, or `sql_pattern` is **not XMI** — it holds Java source (routines/beans) or SQL text (SQL patterns), not an `elementParameter` tree. XML-parsing them is a category error that produced false "parse errors" against a real project. These three types (`NON_XML_TYPES` in [`project_intake.py`](../../tools/project_intake.py)) are therefore classified from their `.properties` only and their `.item` is never XML-parsed. Their `.properties` token is authoritative, so the missing `.item` costs nothing for typing.

## `tRunJob` / `cTalendJob` target id format

**Confirmed:** a call-component target (the job a `tRunJob` / `cTalendJob` invokes) is stored as `PROJECT:_<emfRepositoryId>` — the **called artifact's repository id**, not its label. Resolution (`_normalize_call_target()` in [`project_intake.py`](../../tools/project_intake.py)) strips the `PROJECT:` prefix and matches the bare `_<id>` against the called `.properties` id; the human-readable label is then looked up only for display. Older Studio versions that store a plain label fall through to a raw-value match.

## Project root may be nested in the workspace

**Confirmed:** the Talend project root — the folder that directly contains `talend.project` — is often nested one level under a project-name folder inside the Studio workspace. Point the analyzer at the folder that holds `talend.project`, not the workspace. The `.properties` `xsi:type` vote stays authoritative regardless of how deep the artifact sits in the tree, so folder depth never affects classification.

## ⚠ ESB/route item strings are `[VALIDATE]`

The route/service/routelet detection strings — `RouteItem`, `RouteProcessItem`, `CamelProcessItem`, `RouteletItem`, `ServiceItem` and friends — were taken from Talend's documented model and are **not yet verified against a real ESB project**. They are marked `[VALIDATE]` in the code for the same reason. The real project this module was validated against was DI + REST data services with **no ESB routes**, so these tokens are still unconfirmed. The robust safety net is the **component-prefix histogram**: a route is reliably recognised by its dominant `c*` components even if the exact `.properties` element string differs from what's mapped. When a real ESB project is available, confirm the actual item-element / `xsi:type` spellings and extend `_TYPE_MAP` accordingly.

## Disagreement → `non_standard_flags`

Conflicts between the three votes are **recorded, not silently resolved** — this is the explicit "messy project" signal. `classify_artifact()` populates `non_standard_flags` (and `type_signals` with every raw vote) when:

- **type/folder mismatch** — `.properties` type disagrees with the folder. (Suppressed when the folder is `metadata/`, since connections/contexts legitimately live there.)
- **type/component-prefix mismatch** — a job/route classification disagrees with the `c*`/`t*` histogram.
- **type inferred without `.properties`** — type came from folder or components because no authoritative `.properties` type was present.
- **artifact type unresolved** — all three votes failed; type stays `unknown`.

`type_signals` always carries the breadcrumbs (`folder`, `xsi_type`, `root_element`, `prefix_hist`, and each `type_from_*` vote) so a reviewer can see *why* a type was chosen, not just the verdict.

## CLI

`python tools/talend_discovery.py <project_path>` lists and counts artifacts; `--classify` parses each `.item` for the full three-vote classification (slower); `--json` emits machine-readable output. Flags are printed inline with a `⚠` marker.

## Related

- [`item-file-format.md`](item-file-format.md) — `.item` / `.properties` reading, version-picking rule, and archive-folder caveat that this detection automates.
- [`component-system-catalog.md`](component-system-catalog.md) — the companion: once an artifact is typed as a job/route, its components are mapped to the systems it touches. The `c*`-vs-`t*` distinction is shared with the prefix histogram here.
