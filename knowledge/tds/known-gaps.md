# TDS REST API — docs-vs-reality reconciliation & known gaps

> Phase-1 output of the TDS tooling build. Reconciles the crawled user-guide
> docs (`data-stewardship-user-guide/Cloud/api-*`) against the **live** API at
> `https://tds.eu.cloud.talend.com`, probed 2026-05-29 with a real PAT, and
> revised 2026-05-31 after discovering the campaign-scoped **task** endpoint.
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
| **Tasks** | ✅ **POST `/data-stewardship/api/v1/campaigns/owned/{name}/tasks`** (array of `{type, assignee?, record}`) | ✅ **GET `…/campaigns/owned/{name}/tasks`** (paginates ~200/page) | ⚠️ state transitions / assignment-change not via REST (UI / Studio) | ⚠️ bulk delete not via REST (delete the whole campaign, or Studio `tDataStewardshipTaskDelete`) | **Campaign-scoped** — the standalone `/api/v1/tasks` is 404. `assignee` in the create payload works (sets the steward). See "Tasks" below. |
| **DQ rules** | ❌ | ❌ `/…/rules`, `/dq-rules`, `/dataquality/rules` → **404** (readable only via a data model's `rulesInstances`) | ❌ | ❌ | **No authoring REST endpoint** — UI-only (basic/advanced editor). Advanced-mode language = **DSEL** (now in the qlik-talend skill). See "DQ rules" below. |

## Tasks — the honest picture (revised)

Initial probing hit the **wrong path** (`/api/v1/tasks` → 404) and concluded "no REST". That was wrong: tasks are **campaign-scoped** and fully creatable/readable via REST:

- **Create:** `POST /data-stewardship/api/v1/campaigns/owned/{name}/tasks` with an **array** of `{"type":"RESOLUTION","assignee":<user>,"record":{...}}`. The `record` is a flat object matching the campaign's data-model fields. `assignee` (a tenant username) assigns the task at creation — **live-verified** (5000 tasks created + assigned in one run). Bulk creation via batched arrays scales (~113 tasks/s at 50 fields, ~18/s at 1000 fields).
- **Read:** `GET …/campaigns/owned/{name}/tasks` returns tasks with `currentState`, `valid`, `quality` (per-field 1=valid / negative=invalid), `assignee`, `record`. **Paginates ~200/page** — page or filter server-side for full sets.
- **Validation:** a data-model field typed with a (complete) semantic type makes TDS flag bad values (`valid:false`, `quality[field]<0`).

Still **not** via REST (use UI or Studio components): **state transitions**, **assignment changes after creation**, and **bulk task delete** (delete the whole campaign, or `tDataStewardshipTaskDelete` with TQL). `assignmentStats` on the campaign is **eventually-consistent** — don't treat an immediate 0 as failure.

The kit's `tds_ops.py` ships `task list / get / create` (create defaults `assignee` to `tds.user_email`).

## DQ rules — the honest picture

No **authoring** REST endpoint (UI-only, basic/advanced editor); rules are readable via a data model's `rulesInstances`. The tool does not ship a fake `dqrule create`.

The **advanced-mode rule language** is the **Data Shaping Expression Language (DSEL)** — used to *validate* (not transform), e.g. `NetWeight <= GrossWeight`, `isOfType(CountryOfOrigin, "COUNTRY_CODE_ISO2")`. Plus TDS supplement functions `isInMonth / isInYear / isOfType / isOnDayOfMonth / isOnDayOfWeek`; regex is **RE2/J** (no backreferences). The full DSEL reference is now crawled into the qlik-talend skill (`data-shaping-language-reference-guide`).

## Clean teardown (live-verified)

Repeatable demos are fully tear-down-able via REST, despite the docs implying
delete is UI-only. Order matters because of the reference constraint:

1. `campaign delete <name> --apply`  → DELETE `/campaigns/owned/{name}`
2. `datamodel delete <name> --apply` → now unreferenced, succeeds

A full create→delete cycle (data model + RESOLUTION campaign) was run live and
both objects returned 404 afterwards — zero residue.

## Consequences for the tool

- Full, real CRUD ships for **data models, campaigns, semantic types** (incl. deletes → clean demo teardown) and **tasks** (`task list/get/create`, assigned by default).
- **Task transitions/reassignment & DQ-rule authoring**: no REST — surfaced as clear UI/Studio messages in the CLI (`task info`, `dqrule info`), never silent no-ops.
- Campaign create requires a data model first (`schemaRef`) and a valid owner username; tasks need a `record` matching the model. Owner/assignee = the authenticated tenant user (configured locally, never committed).
