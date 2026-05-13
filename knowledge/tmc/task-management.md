# TMC Task Management — Update, Promote, Execute

Reference for what we need to do *after* `cloudpublisher-maven-plugin:publish` has uploaded a new artifact version to TMC: bind tasks to that new version, move artifacts/tasks between environments, trigger runs.

Companion to [api-maven-publish.md](api-maven-publish.md) (build/publish side).

## Mental model

TMC organises everything around **environments** (e.g. `dev`, `tst`, `uat`, `prd`). Each environment contains one or more **workspaces** (a.k.a. *spaces*). Inside a workspace live:

- **Artifacts** — the published microservice / job ZIPs uploaded by the Cloud Publisher. Each has a version chain (`3.0.1`, `3.0.2`, …).
- **Tasks** — runtime configurations that pin one specific artifact version + parameters + run profile. A task is what actually executes.
- **Plans** — orchestrations of multiple tasks.
- **Promotions** — copy operations between environments.

Key distinction: **publishing a new artifact version does not automatically update any task.** A task always points to a specific artifact version, and that pointer is updated independently — manually, via the *auto-update* flag, or via the Public API.

## Versioning rules

- **Artifact version** is the version uploaded by the publisher (controlled on our side by the local `pom.xml` + the cloudpublisher's auto-increment from TMC's last version).
- **Task version** is independent and increments automatically when "the components used in it, its context variables or its artifact" change. Run-config changes (timeout, schedule, engine, run profile) do **not** bump the task version.
- **Auto-update flag** — per-task option *"Always use the latest available artifact version"*. When on, a new published artifact version is picked up by the task automatically. **Disabled by default after a promotion** (TMC sets this off on first promotion to a new env to prevent surprise version jumps).
- After a **promotion**, the auto-update does *not* trigger — the task in the target env must be explicitly bound to the promoted version.

## API surface — live spec

Qlik retired the old monolithic `tmc/swagger-ui.html`. Authoritative reference is now the **Talend Cloud APIs portal** ([talend.qlik.dev/apis/](https://talend.qlik.dev/apis/)), where each functional area is its own versioned product. The portal always reflects the current shape — **do not copy endpoint paths into this repo**, follow the link.

For the workflows in this doc the relevant products are:

| Workflow concern | API product | Spec |
|---|---|---|
| Read artifacts + versions, CRUD tasks/plans/promotions, pause/resume | **Orchestration** | [orchestration spec](https://talend.qlik.dev/apis/orchestration/2021-03/) |
| Trigger / terminate / inspect executions of tasks, plans, promotions | **Processing** | [processing spec](https://talend.qlik.dev/apis/processing/2021-03/) |
| Run logs and execution history | Execution Logs + Execution History Search | [execution-logs](https://talend.qlik.dev/apis/execution-logs/2021-03/), [execution-history-search](https://talend.qlik.dev/apis/execution-history-search/2021-03/) |
| Run-time metrics (duration, success rate, etc.) | Observability Metrics | [observability-metrics](https://talend.qlik.dev/apis/observability-metrics/2021-03/) |
| Workspace / engine / role permissions if scripting access | Workspace Permissions, Identities Management, Service Accounts | [workspace-permissions](https://talend.qlik.dev/apis/workspace-permissions/2021-03/), [identities](https://talend.qlik.dev/apis/identities-management/2021-03/), [service-accounts](https://talend.qlik.dev/apis/service-accounts/2021-03/) |
| OAuth2 client-credentials flow for service accounts | OAuth | [oauth](https://talend.qlik.dev/apis/oauth/2021-03/) |
| Audit trail for compliance | Audit Logs | [audit-logs](https://talend.qlik.dev/apis/audit-logs/2021-03/) |

The full catalogue (all 18+ products incl. Connections, Crawler, Dataset, IP Allowlist, Sharing, SCIM v2, SSO Role Mapping, Seats & Subscription, Dynamic Engine, etc.) lives at the portal index above.

> **Heads-up:** The *Orchestration* spec covers definition (CRUD of tasks, plans, promotions, artifacts). The *Processing* spec covers everything that **runs** something (POST executions, terminate, status). When the old TMC docs talked about `POST /tmc/v…/executions/...`, that path is gone — replace with the corresponding `POST /processing/executions/...` from the Processing spec.

## Authentication

All API calls use a Personal Access Token (PAT) or service-account token:

```
Authorization: Bearer <token>
Content-Type: application/json
```

Region base URLs (path under each is the API product path, e.g. `/orchestration/...`, `/processing/...`):

| Region | Base |
|---|---|
| EU | `https://api.eu.cloud.talend.com` |
| US | `https://api.us.cloud.talend.com` |
| US-West | `https://api.us-west.cloud.talend.com` |
| AP | `https://api.ap.cloud.talend.com` |
| AU | `https://api.au.cloud.talend.com` |

The kit's `tmc_release.py` builds the base URL from `tmc.region` in your `talend.config.json` (default `eu`).

Permissions:

| Action | Required role |
|---|---|
| List/get tasks, get artifact versions | any read role on the space |
| Update task (bind new artifact version) | `Editor` (Author) on task space + at least read on artifact space — or `TMC_OPERATOR` for API calls |
| Promote artifact/task | promotion permission on both source and target envs |
| Execute task | execution permission on the task's space |

## Workflow A — Bind a task to a new artifact version

After our build pipeline publishes (e.g.) `i5xx_api_example` 3.0.0 → 3.0.1, the existing task referencing 3.0.0 keeps using 3.0.0 until updated.

### Option A1 — auto-update flag (preferred when safe)

Set the per-task option *"Always use the latest available artifact version"* via the UI (or in the task payload via API). With this on, the task picks up the next published version automatically.

> Note: TMC disables this flag automatically after a first promotion. So promoted-into envs always need a manual bump on the first upgrade.

### Option A2 — UI

Tasks tab → right-click the task → **Update** → confirm. Updates one or many tasks at once.

If an artifact has new mandatory parameters, the dialog forces you to fill them. Existing parameter values are preserved — toggle *"Override parameter values with artifact defaults"* if you want them reset.

### Option A3 — Public API ([Orchestration](https://talend.qlik.dev/apis/orchestration/2021-03/))

Two steps using the Orchestration API:

1. **Discover** — list tasks for a workspace, optionally filtered by artifact (see the spec's `Tasks` section). The query parameters and supported filters are versioned in the spec.
2. **Update** — full update via `PUT` only. `PATCH` does **not** accept the `artifact` field (HTTP 400 `unrecognized field: artifact`, verified 2026-05-07), so for an artifact-version bump you have to use `PUT` with the full task payload.

> **Critical for `PUT`:** the payload must contain **all** existing fields of the task. Any field omitted is set to `null`. Recommended pattern: GET the task first, then transform and PUT.
>
> Two shape gotchas between the GET response and the PUT body (verified 2026-05-07):
> - GET returns a nested `workspace: { id, name, environment, ... }` object; PUT expects a flat `workspaceId` string. Convert.
> - GET includes `id` (task ID) and `version` (server-managed task version like `"10.12"`). Drop both — the path already carries the ID, and including `version` is rejected.
>
> Everything else (`name`, `description`, `artifact`, `tags`, `parameters`, `runtime`, etc.) must be carried over unchanged. Mutate only `artifact.version`.

### The GET → modify → PUT pattern is mandatory for `bind`

`bind` (changing the artifact version on a task) is just a `PUT` on the task entity — and `PUT` requires the **full** task body. There is no `PATCH` for the `artifact` field (HTTP 400 `unrecognized field: artifact`, see above). So the workflow is fixed:

1. `GET /orchestration/executables/tasks/{id}` — fetch current task config
2. modify only the field(s) you want to change (here: `artifact.version`)
3. `PUT` the full body back

Any field omitted from the PUT body is set to `null` by the server. This pattern is correct in principle — the bug is in step 1, see next section.

### Where things actually live: task body vs `/run-config` sub-resource (verified 2026-05-08, refined 2026-05-09)

A task has **two independent resources** in the API:

```
GET / PUT /orchestration/executables/tasks/{id}             -- task body
GET / PUT /orchestration/executables/tasks/{id}/run-config  -- runtime config
DELETE   /orchestration/executables/tasks/{id}/run-config   -- stop schedule only
```

**Task body** (`/tasks/{id}`) — fields returned by GET (verified):
`id, name, description, workspace, version, artifact, parameters, taskPauseDetails, tags`. This is what `cmd_bind` PUTs back when changing `artifact.version`.

**Run-config** (`/tasks/{id}/run-config`) — separate resource, GET returns:
`runtime: { type, id, runProfileId }`, `microservicePort`, `deploymentStrategy`, `parallelExecutionAllowed`, `trigger: { type, atTimes, … }`, `lineage`. `microservicePort` returns as a string; absent/unset means "auto".

**Bind ↔ run-config — empirical truth (verified 2026-05-09):**

| Bind scenario | Effect on run-config |
|---|---|
| PUT task body with **same** `artifact.version` (no-op) | run-config fully preserved — all fields untouched |
| PUT task body with a **different** `artifact.version` (real bump) | server silently sets `microservicePort` to `null`. `runProfileId`, `runtime.id` (engine cluster), `deploymentStrategy`, `parallelExecutionAllowed`, `trigger`, `lineage` all stay intact. |

The "port goes to auto on a real version change" is reproducible and is almost certainly a Talend Cloud server-side bug (the resources are documented as independent, and only this single field is reset). Worth raising as a Talend/Qlik support ticket.

**Mitigation in `cmd_bind`:** GET `/run-config` *before* the task PUT, then PUT it back *after*. This restores `microservicePort` regardless of whether the bind was a no-op or a real bump, so callers don't have to think about it. Implemented in `tmc_release.py` 2026-05-09.

**Promotion side (verified 2026-05-09):** Promotion **does** copy run-config — the target task's existing run-config is preserved across a promote, and a real `artifact.version` change via promotion does **not** trigger the port-null bug. The port-null bug is specific to the direct `PUT /orchestration/executables/tasks/{id}` codepath; the server-side promotion codepath does not hit it.

**The list endpoint shows `runtime` at the task level** (`GET /orchestration/executables/tasks?…` items return `runtime: { … }`) but that's a denormalised view — the storage of record is `/run-config`.

### Per-project port and run-profile-ID tables

A project that runs multiple data-service microservices on a Remote Engine needs:

- a **port map** per API (so the reverse-proxy can route),
- a **run-profile-ID map** per env (so each task gets the right JVM args bundle).

Both should be maintained in the consuming project's own `docs/` — they're Layer-3 data, not portable Talend mechanics. The relevant TMC behaviour: run-profile IDs are *not* promoted along with tasks, so a freshly promoted task in tst/uat/prd needs an explicit `PUT /run-config` to set both port and run profile.

To find the latest published version of an artifact, use the Orchestration `Artifacts` endpoints (list, get by id, get by id+version). Note that artifact versions in TMC are **fully qualified with a timestamp** — e.g. `3.0.2.20260705052210`, not just `3.0.2`. The full string is what goes into the task's `artifact.version` field.

## Workflow B — Promote between environments

Promotion = copy artifacts/tasks/plans/etc. from source env to target env. It is **not** a publish — promotion targets an environment that already exists, the artifacts are copied over.

### What can be promoted

Job artifacts, pipeline artifacts, tasks (job + pipeline), plans, Studio connections, Studio resources, task schedulers, spaces, Remote Engines/Gen2, engine clusters, run profiles. **Personal spaces cannot.**

### Caveats

- **Naming:** environment + space names must be `[A-Za-z0-9_]` only — webhooks break otherwise.
- **Secured connection params** are reset to literal `<change me>` in the target env and need re-entry.
- **New Remote Engines** require manual pairing post-promotion.
- **Existing parameter values** on tasks in the target env persist on update; only newly added parameters are added.
- **Auto-update flag** for promoted artifacts is forced **off** on first promotion to a new env.
- Studio connections of differing types between envs trigger an error.

### UI workflow

Promotions menu → New promotion → pick source/target env → select objects → run *promotion analysis* (lists conflicts) → resolve conflicts → execute.

### API

Two distinct concerns:

- **Define / configure** the promotion — creating it, listing it, running analysis, accepting/rejecting conflicts, deleting it. Lives in the [Orchestration](https://talend.qlik.dev/apis/orchestration/2021-03/) spec (`Promotions` section). Note that `POST /orchestration/executables/promotions/{id}` runs *promotion analysis*, not the actual transfer.
- **Execute** the promotion (i.e. perform the transfer) — lives in the [Processing](https://talend.qlik.dev/apis/processing/2021-03/) spec under its execution endpoints for promotions.

The legacy `POST /tmc/v1.2/executions/promotions` URL referenced in older Qlik help pages is from the deprecated TMC swagger — use the Processing API equivalent instead.

**Reusable promotion definitions.** In our setup the env-pair promotions (`dev to tst`, `tst to uat`, `uat to prd`, etc.) are already defined as one-off `Promotion` entities. Don't create a new one per release — list them via `GET /orchestration/executables/promotions`, find the right env-pair, and reuse its id.

**Per-execution scope (`advanced`).** The promotion definition itself is just a source/target env mapping; *what* gets promoted is selected per execution via `advanced.artifactId` + `advanced.artifactType` in the `POST /processing/executions/promotions` payload. `artifactType` accepts:

| Value | Promotes |
|---|---|
| `ACTION` | a single artifact version (the artifact only, not its task) |
| `FLOW` | a task; the artifact version the task is bound to is carried along |
| `PLAN` | a plan |
| `WORKSPACE` | the entire workspace |

Despite the field name, `artifactId` holds the ID of *whatever entity* matches `artifactType` — for `FLOW` you pass the **task ID** there, not the artifact ID. Verified 2026-05-07.

**Typical microservice promotion (this project).** The dev task is updated to the new artifact version (Workflow A), then a `FLOW` promotion is executed with the dev task ID. The artifact rides along automatically. The response contains `targetId` for the corresponding task in the target env — that's the ID you use to deploy/run on the target.

## Workflow C — Trigger execution after update

After a task is on the new version, the next scheduled run will use it automatically. To force an immediate run, use the [Processing](https://talend.qlik.dev/apis/processing/2021-03/) API:

- **Run a task** — POST under `/processing/executions` (returns an `executionId`)
- **Run a plan** — POST under `/processing/executions/plans`
- **Run a promotion** — POST under `/processing/executions/promotions`
- **Get status** / **terminate** — GET / DELETE on the corresponding execution-id path

Exact path shapes, payloads, and any required `executable`/`keepTargetResources`-style fields are in the spec linked above. The old `POST /tmc/v…/executions` endpoints are deprecated.

For run logs and history afterwards, see the [Execution Logs](https://talend.qlik.dev/apis/execution-logs/2021-03/) and [Execution History Search](https://talend.qlik.dev/apis/execution-history-search/2021-03/) APIs.

## Workflow D — Undeploy / redeploy / cycle a microservice (verified 2026-05-08)

For ESB microservices (`artifact.type = "data_service"`) on a Remote Engine, "deploy" and "undeploy" map to execution operations on the bound task — there is no separate microservice-deploy resource.

### Lifecycle mapping

| TMC concept              | API call                                                       | Notes |
|---|---|---|
| Deploy / start / restart | `POST /processing/executions` body `{"executable": <taskId>}` | If a previous execution is still bound to the same engine port, the new one will fail with *"Can't configure server port N"* — undeploy first. |
| Undeploy / stop          | `DELETE /processing/executions/<executionId>`                  | Same call terminates batch executions; for microservices it tears down the OSGi bundle on the engine. **Returns `text/plain`, not JSON** — `Accept: application/json` produces HTTP 406. |
| Status of a microservice | `GET /processing/executables/tasks/<taskId>/executions`        | A microservice is "deployed" while at least one execution has `status="executing"`. After undeploy the same execution flips to `execution_successful`. |

### Status values

Per the [Processing spec](https://talend.qlik.dev/apis/processing/2021-03/), executions can be in one of: `dispatching, deploy_failed, executing, execution_successful, execution_rejected, execution_failed, terminated, terminated_timeout, terminated_shutdown`. For microservices the ones we actually see in this project:

| status                   | meaning |
|---|---|
| `dispatching`            | engine is preparing the bundle — pre-running, transient |
| `executing`              | microservice deployed and running |
| `execution_successful`   | clean stop (e.g. after `DELETE`) — for batch jobs: completed |
| `execution_failed`       | crashed (port conflict, lock contention, ungraceful shutdown, etc.) |
| `deploy_failed`          | engine refused the deployment outright |

**A microservice counts as "deployed" while its execution is `dispatching` or `executing`** — anything else is dead/stopped/never-started.

### Deploy receipt ID ≠ actual execution ID (verified 2026-05-09)

`POST /processing/executions` returns `{"executionId": "..."}` — but **that ID is a deploy *receipt*, not the actual running execution's ID**. The execution that ends up in `GET /processing/executables/tasks/<taskId>/executions` (and is the thing you DELETE to undeploy) has a *different* `executionId`. Looking up the receipt ID via `GET /processing/executions/<receiptId>` returns HTTP 404.

Implication for health-check tooling: don't poll on the receipt ID. Instead, snapshot the existing execution IDs *before* the POST, then poll the task's executions list for any *new* ID with `status=executing` (or `dispatching` as a transient pre-state). The new ID typically appears within 5–15 s on dev/tst single-engine clusters; allow up to ~60 s on slow dispatch. If a new execution shows `execution_failed` / `deploy_failed`, the deploy is dead — abort.

This is what `cmd_deploy` in `tmc_release.py` should do; today it only POSTs and returns the receipt without polling. Consumers that need real "deployed and serving" confirmation must implement the pre/post-snapshot polling themselves (see `/tmp/deploy_phase.sh` reference implementation, 2026-05-09).

### `bind` ≠ deploy — the new version doesn't auto-take-effect

> "Any configuration update between a start/stop is ignored by the deployed microservices. To avoid recovery, microservices should be undeployed."
> — [Talend Remote Engine docs](https://help.qlik.com/talend/en-US/remote-engine-user-guide-linux/Cloud/microservices)

`bind` (= update the task to point at a new artifact version) and "deploy" are intentionally separate concerns:

- **`bind` alone** is legitimate: it stages the new version on the task without disturbing the running endpoint. Useful when you want to ship to a stable env without an outage window, or pre-stage a change for a coordinated cutover.
- **`bind` followed by undeploy + redeploy** is required when you want the new version to actually run. There is no implicit restart — Talend's docs explicitly say running microservices ignore config updates until undeployed.

The `release`-style "go all the way live now" flow therefore needs `bind → undeploy → redeploy`, in that order. The ad-hoc "just pin it for later" flow stops at `bind`. Pick the one that matches the intent.

### Detecting whether a microservice is actually running (UAT/PRD reality check)

The execution-listing endpoints — `GET /processing/executables/tasks/{taskId}/executions` and the cross-task `GET /processing/executables/tasks/executions?environmentId=…` — are **not reliable** on UAT/PRD for long-running microservices. Verified 2026-05-10: services that have been continuously `executing` for weeks/months disappear from these endpoints (`total=0`) even though the OSGi bundle is demonstrably alive on the engine. The TMC UI shows them correctly because it uses a different (non-public) data channel.

The Talend Public API does not expose any `lastSeen` / `lastHeartbeat` / `runtimeStatus` field on tasks or executions either — there's no first-class "is this running" probe.

**Reliable methods, in order of preference:**

1. **HTTP probe via reverse-proxy.** Hit a known auth-protected REST path of the API (e.g. `https://api-<env>.example.com/customer-master/v1/customers`). HTTP 401 means the bundle is up and the auth filter is responding — definitive *running* signal. Connection refused / timeout = down. HTTP 404 with empty body = path not routed (could be wrong path or service down — ambiguous). Maintain a per-API `health_probe_url` mapping if you script this.
2. **SSH read-only inspection on the engine VM.** `ps -ef | grep <jar>` plus `sudo ss -tlnp | grep <pid>` confirms both the Java process and the listening port. Most authoritative, but needs SSH access — usually only available on lower environments.
3. **Public API as last fallback.** Treat `total=0` from `/executions` as "unknown", not as "not running".

Tracked as a Talend support-ticket TODO — see [`known-bugs.md`](known-bugs.md).

### `POST /processing/executions` self-heals an orphan deploy

Verified 2026-05-10 against UAT i520/i530/i556: when a task has been promoted to a new artifact version but the engine still runs the old bundle (and the public API hides the alive execution), a plain `POST /processing/executions {executable: <taskId>}` — **without any prior DELETE** — succeeds. TMC undeploys the old bundle automatically and starts the new one. Within ~5–10 s, two new `executing` executions appear (multi-engine cluster), the reverse-proxy never observes a 5xx gap (HTTP 401 stays consistent through the swap), and the new executions are visible in the public API again (the "hidden retention" only affects the long-running orphan, not freshly-started ones).

So the recipe for "promoted but stale bundle on UAT/PRD":
1. Probe via reverse-proxy → 401 → service is alive but on the *old* version.
2. `POST /processing/executions` for the task — no DELETE, no executionId needed.
3. Poll `/executables/tasks/{id}/executions` for new executing IDs (typically appears within 5 s, both engines populated within 15 s).

This is **not** documented behaviour and should not be relied on for batch jobs (semantics may differ — it might *add* a parallel execution rather than replacing). Verified for microservices (`artifact.type = "data_service"`) only.

### When TMC reports `execution_failed` but the bundle is actually running

Sometimes (observed 2026-05-09 on TST) the Processing API marks an execution as `execution_failed` while the OSGi bundle on the engine is in fact still serving requests. Mismatch between TMC's view of the bundle and the engine's reality.

If you see this — execution `*_failed` in TMC, microservice still healthy on its port — **`DELETE /processing/executions/<failed-execution-id>` is worth trying first**, even though the execution is "already failed". The DELETE often reaches through, tears the bundle down properly, and unblocks the next deploy. Without it, a fresh `POST /processing/executions` may fail with a port-conflict because the engine still holds the bundle on the configured port.

So when you're stuck with a "failed but running" task: try the DELETE on the failed-id first, *then* re-deploy. Cheap, safe, often fixes it. Direct Karaf intervention is the last resort — and only with explicit user approval (see CLAUDE.md "Remote Engine SSH access — operational rules").

### Cascading port conflicts when fixing port assignments in bulk

Setting `microservicePort` on `/run-config` is a TMC-level config change — it does **not** restart the bundle on the engine. The bundle keeps its current (possibly random) port until the next undeploy + deploy cycle. So when migrating multiple tasks from `auto` to fixed ports, you can hit a cascading conflict: undeploy task A, set port 5072 in TMC, try to deploy A → engine refuses because task B is still squatting on 5072 (B was on `auto` and the engine had assigned 5072 to it during a prior fresh start). Even though A's TMC config now says 5072, B holds the actual socket.

The robust pattern is **mass undeploy first → wait → sequential deploy** rather than per-task undeploy/deploy. Stop *all* affected tasks, give the engine ~30–60 s to release ports, then deploy each one. With every target port unoccupied at deploy time, the engine binds cleanly. Reference impl: `/tmp/mass_redeploy_tst.sh` (2026-05-09).

### Filtering tasks by name + env

Listing all i5xx tasks on dev in one shot:

```
GET /orchestration/executables/tasks?name=i5&environmentId={dev_env_id}
```

`name` is a **prefix** match. `environmentId` requires the env's UUID, not its name — fetch from `GET /orchestration/environments`.

### One-engine vs multi-engine clusters

For a Remote Engine **Cluster** with multiple engines (uat / prd here), the same task has **one `executing` execution per engine**. Undeploy must DELETE *all* of them. `dev` and `tst` use a single-engine cluster, so there's always exactly one. List the executions, filter `status=="executing"`, DELETE each.

### Hidden retention behaviour on uat (open question, 2026-05-08)

`GET /processing/executables/tasks/<taskId>/executions` on uat returns `total=0` for several i5xx tasks even when the microservice is demonstrably running. Some other tasks on the same env return historical executions normally. None of the obvious query parameters (`from=`, `status=`, `limit=`, `includeFinished=`, `all=`) help — `from`/`limit` produce HTTP 400, the rest produce `total=0`. Looks like an undocumented retention or visibility cutoff (not pagination). For uat/prd, fall back to the TMC UI's *Run History* tab to see live executions.

### Ready-made tooling

[`cimt-talend/scripts/tmc_microservice_ops.py`](../scripts/tmc_microservice_ops.py) wraps all four commands (`list / undeploy / redeploy / cycle`) for `name=i5` + env. Destructive ops are hard-limited to dev + tst — uat/prd use the TMC UI.

## Sources (Qlik help pages — concepts and rules)

- [Changing the artifact version used in a Job task](https://help.qlik.com/talend/en-US/management-console-user-guide/Cloud/changing-artifact-version-used-in-job-task)
- [Updating Job tasks with latest artifact version](https://help.qlik.com/talend/en-US/management-console-user-guide/Cloud/updating-job-tasks-with-latest-artifact-version)
- [Get tasks to be updated (API tutorial)](https://help.qlik.com/talend/en-US/use-api-to-update-artifact-in-tasks/Cloud/get-tasks-to-be-updated)
- [Update tasks with new artifact version (API tutorial)](https://help.qlik.com/talend/en-US/use-api-to-update-artifact-in-tasks/Cloud/update-tasks-with-new-artifact-version)
- [Promotion rules](https://help.qlik.com/talend/en-US/management-console-user-guide/Cloud/promotion-rules)
- [Task versioning](https://help.qlik.com/talend/en-US/management-console-user-guide/Cloud/task-version-in-tmc)

API specs (always go to the portal for endpoint shapes — anything copied here will rot):

- [Talend Cloud APIs portal index](https://talend.qlik.dev/apis/)
- [Orchestration](https://talend.qlik.dev/apis/orchestration/2021-03/) — definitions / CRUD
- [Processing](https://talend.qlik.dev/apis/processing/2021-03/) — executions / engines
