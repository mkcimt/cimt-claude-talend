# Talend Data Stewardship (TDS) REST API — reference

Sourced from the Qlik user guide (`data-stewardship-user-guide/Cloud/api-*`)
and **verified live** 2026-05-29 against `https://tds.eu.cloud.talend.com`.
The kit's tool for this API is [`tools/tds_ops.py`](../../tools/tds_ops.py)
(client: [`tools/tds_client.py`](../../tools/tds_client.py)). For what the API
cannot do, see [`known-gaps.md`](known-gaps.md).

## Auth & base URL

- `Authorization: Bearer <PAT>` — a Talend Cloud Personal Access Token works directly.
- Base URL `https://tds.{region}.cloud.talend.com` (region list: help.qlik.com → "Accessing Talend Cloud applications").
- Config for the tool: `tds.base_url` (or `tds.region`), `tds.token`, `tds.user_email` in `.claude/talend.local.properties` (gitignored), or `TALEND_TDS_*` env vars.
- Swagger UI exists at `/docs/api/swagger-ui.html` but the aggregated spec is not retrievable with an API token (SPA-served); the endpoints below were confirmed by direct calls.

## Services

| Service | Prefix | Objects |
|---|---|---|
| Data Stewardship | `/data-stewardship/api/v1` | campaigns |
| Schema service | `/schemaservice/api/v1/schemas/org.talend.schema` | data models |
| Semantic service | `/semanticservice` | semantic types |

## Data models — `schemaservice`
- **List**  `GET /schemaservice/api/v1/schemas/org.talend.schema` → array
- **Read**  `GET …/{name}` → full model incl. `fields[]` and `rulesInstances[]`
- **Create** `POST …` body `{name, displayName, description, fields:[{name,displayName,type,required,constraints?}]}` → 200. Field types: `integer|text|decimal|URL|date|boolean|…`; `decimal` takes `constraints:[{name:"scaleDecimal",value:N}]`. Duplicate name → 400 `SCHEMA_NAME_ALREADY_EXISTS`.
- **Update** `PUT …/{name}` (GET, modify, PUT back)
- **Delete** `DELETE …/{name}` → 400 `SCHEMA_NOT_DELETABLE_REFERENCED` while a campaign references it.
- Citations: `…/api-tds-create-datamodel`, `…/api-tds-read-datamodel`, `…/api-tds-update-datamodel`.

## Campaigns — `data-stewardship`
- **List** `GET /data-stewardship/api/v1/campaigns/owned` (owned) or `…/campaigns` (all) → array
- **Read** `GET …/campaigns/{name}` (name = the generated id-like string; pattern `^[a-z][a-z\d-]*$`)
- **Create** `POST …/campaigns/owned` body `{campaign:{name,label,description,owners:[username],taskType,schemaRef:{namespace:"org.talend.schema",name,version,displayName},taskResolutionDelay:{value,unit},workflow:{name,states:[…]}}, participants:{Supervisor:[…],Validator:[…]}}` → 200 (response has `id`). `taskType` ∈ RESOLUTION|MERGING|GROUPING|ARBITRATION (workflow differs per type; RESOLUTION example templated in the tool).
- **Update** `PUT …/campaigns/owned` — only `label` + `participants` are editable.
- **Delete** `DELETE …/campaigns/owned/{name}` (by NAME; `/campaigns/{name}` and `/campaigns/{id}` → 405).
- Requires a data model first (referenced via `schemaRef`). Owner must be a real tenant username.
- Citations: `…/api-tds-create-campaign`, `…/api-tds-update-campaign`.

## Semantic types — `semanticservice`
Lifecycle (the tool's `semantic create` runs all of it):
1. `POST /semanticservice/categories/sandbox` → `{id}` (201)
2. `PATCH /semanticservice/categories/{id}` — define the type:
   - DICT: `{name,label,type:"DICT",validationMode}` (+ `POST /semanticservice/documents {categoryId,values:[[v]]}` for entries)
   - REGEX: `{…,type:"REGEX",validationMode,regEx:{mainCategory,validator:{patternString}}}` — mainCategory ∈ Alpha|AlphaNumeric|Numeric|BLANK|NULL
   - COMPOUND: `{…,type:"COMPOUND",children:[childCategoryId]}`
   - validationMode ∈ SIMPLIFIED | EXACT | EXACT_IGNORE_CASE_AND_ACCENT
3. `PATCH /semanticservice/v2/categories/{id}/draft` (async, 204)
4. `GET /semanticservice/v2/categories/{id}/draft/status` → poll until FINISH
5. `POST /semanticservice/categories/{id}/publish` (204)
- **List** `GET /semanticservice/categories`; **Delete** `DELETE /semanticservice/categories/{id}`.
- Citations: `…/api-tsd-create-sandbox`, `…/api-tsd-edit-sandbox`, `…/api-tsd-save-draft`, `…/api-tsd-save-status`, `…/api-tsd-publish-draft`.

## Tasks — `data-stewardship` (campaign-scoped)
Tasks are the records inside a campaign. The standalone `/api/v1/tasks` is **404** — always go through the campaign:
- **List** `GET /data-stewardship/api/v1/campaigns/owned/{name}/tasks` → array; each task has `currentState`, `valid`, `quality` (per-field 1=valid / negative=invalid), `assignee`, `record`. **Paginates ~200/page.**
- **Create** `POST …/campaigns/owned/{name}/tasks` with an **array** of `{"type":"RESOLUTION","assignee":<username>,"record":{<field>:<value>,…}}`. `record` matches the data-model fields; `assignee` assigns at creation. Batched bulk insert scales (~113 tasks/s @50 fields … ~18/s @1000 fields).
- **Not via REST:** state transitions, assignment change after creation, bulk delete (delete the campaign, or Studio `tDataStewardshipTaskDelete`/TQL). `assignmentStats` is eventually-consistent.
- Tool: `tds_ops.py task list|get|create` (create defaults `assignee` to `tds.user_email`).

## DQ rules — UI-only authoring; language = DSEL
No authoring REST endpoint (UI basic/advanced editor); readable via a data model's `rulesInstances`. Advanced-mode language = **Data Shaping Expression Language (DSEL)**, used to validate: e.g. `NetWeight <= GrossWeight`, `isOfType(CountryOfOrigin, "COUNTRY_CODE_ISO2")`. TDS functions: `isInMonth/isInYear/isOfType/isOnDayOfMonth/isOnDayOfWeek`; regex = RE2/J (no backreferences). Full DSEL reference: the `data-shaping-language-reference-guide` in the qlik-talend skill. Citations: `…/tds-dqr-explang`, `…/operators`, `…/creating-data-quality-rule`.
