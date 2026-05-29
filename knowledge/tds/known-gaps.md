# TDS REST API — docs-vs-reality reconciliation & known gaps

> Phase-1 output of the TDS tooling build. Reconciles the crawled user-guide
> docs (`data-stewardship-user-guide/Cloud/api-*`) against the **live** API at
> `https://tds.eu.cloud.talend.com`, probed 2026-05-29 with a real PAT.
> Method: documented endpoints verified live; method matrix via OPTIONS
> (`schemaservice`/`semanticservice` give real `Allow` headers); the
> `data-stewardship` service returns a generic Spring `Allow` for every path,
> so its endpoints were discriminated by GET + 404-body shape.

## Auth (confirmed)

- Bearer **Personal Access Token** works directly — no `/data-stewardship/login` exchange needed. `Authorization: Bearer <PAT>`.
- Base URL per region: `https://tds.{region}.cloud.talend.com` (here: `eu`).
- Three live API services: `data-stewardship` (campaigns), `schemaservice` (data models), `semanticservice` (semantic types). A "history" service is referenced in the docs but its API base is not reachable at the guessed paths (the SPA catches them); deferred.

## Capability matrix (live-verified)

| Object | Create | Read | Update | Delete | Notes |
|---|---|---|---|---|---|
| **Data model** (`schemaservice`) | ✅ POST `/schemaservice/api/v1/schemas/org.talend.schema` | ✅ GET `…/{name}` and collection GET | ✅ PUT `…/{name}` | ✅ **DELETE `…/{name}`** — but 400 `SCHEMA_NOT_DELETABLE_REFERENCED` while a campaign references it → delete referencing campaigns first | name allows `_`/mixed case; dup name → 400 `SCHEMA_NAME_ALREADY_EXISTS` |
| **Campaign** (`data-stewardship`) | ✅ POST `/data-stewardship/api/v1/campaigns/owned` | ✅ GET `…/campaigns/owned`, `…/campaigns`, `…/campaigns/{name}` | ✅ PUT `…/campaigns/owned` (label + participants only) | ✅ **DELETE `…/campaigns/owned/{name}`** (by NAME; `/campaigns/{name}` and `/campaigns/{id}` → 405) — live-verified | **name pattern `^[a-z][a-z\d\-]*$`** (lowercase/digits/hyphen, NO underscore); needs a pre-existing data model via `schemaRef` |
| **Semantic type** (`semanticservice`) | ✅ POST `/semanticservice/categories/sandbox` | ✅ GET `/semanticservice/categories` | ✅ PATCH `/categories/{id}`, draft `PATCH /v2/categories/{id}/draft` (async → poll `/draft/status`), publish `POST /categories/{id}/publish` | ✅ **DELETE `/categories/{id}`** (Allow header confirms) | sandbox→draft→publish lifecycle; types DICT/REGEX/COMPOUND |
| **Tasks** | ❌ no REST endpoint | ❌ `/…/api/v1/tasks` → **404** | ❌ | ❌ | **Not exposed via TDS REST API.** No `api-*-task*` doc page exists. Tasks are children of campaigns, created/queried/updated via **Studio components** (`tDataStewardshipTaskInput/Output/Delete`) using **TQL**, or the UI. See "Tasks" below. |
| **DQ rules** | ❌ | ❌ `/…/rules`, `/dq-rules`, `/dataquality/rules` → **404** | ❌ | ❌ | **No REST endpoint** under any probed path. UI-only (basic/advanced rule editor). |

## Tasks — the honest picture

The user asked for "tasks erstellen, ändern". The TDS **REST API does not expose task CRUD** — confirmed by 404 on every `/api/v1/tasks*` path and by the absence of any task API page in the user guide. In TDS, tasks are the *records inside a campaign* and are managed by:
- **Studio components** `tDataStewardshipTaskInput` (load/create tasks into a campaign), `tDataStewardshipTaskOutput`, `tDataStewardshipTaskDelete`, filtered with **TQL** — i.e. a Talend job, not a REST call.
- The **Data Stewardship UI** (manual resolution, transitions, assignment).

→ Programmatic task creation for demos is therefore a **Studio-job concern**, out of scope for this REST tool. The tool will instead make demo *task seeding* easy by (a) creating the campaign and (b) emitting a ready-to-run task-seed payload/CSV + documenting the `tDataStewardshipTaskInput` path. Tracked as a follow-up, not faked here.

## DQ rules — the honest picture

No REST endpoint found. DQ rules are authored in the UI and associated to a data model there. The tool documents this as UI-only; it will not ship a fake `dqrule create`.

## Clean teardown (live-verified)

Repeatable demos are fully tear-down-able via REST, despite the docs implying
delete is UI-only. Order matters because of the reference constraint:

1. `campaign delete <name> --apply`  → DELETE `/campaigns/owned/{name}`
2. `datamodel delete <name> --apply` → now unreferenced, succeeds

A full create→delete cycle (data model + RESOLUTION campaign) was run live and
both objects returned 404 afterwards — zero residue.

## Consequences for the tool

- Full, real CRUD ships for **data models, campaigns, semantic types** (incl. deletes → enables clean demo teardown, better than the docs implied).
- **Tasks & DQ rules**: no REST verbs. Documented here + surfaced as clear "UI-only / Studio-component" messages in the CLI, never silent no-ops.
- Campaign create requires a data model first (`schemaRef`) and a valid owner username (the authenticated tenant user; configured locally, never committed).
