# TMC Microservice Lifecycle — Quick Reference

For ESB-style data-service microservices (`artifact.type = "data_service"` in TMC).

## API operations

| Operation | Endpoint |
|---|---|
| Deploy / restart | `POST /processing/executions` — body: `{"executable": <taskId>}` |
| Undeploy | `DELETE /processing/executions/<executionId>` — **`Accept: text/plain`** (JSON Accept yields HTTP 406) |
| Status / running executions | `GET /processing/executables/tasks/<taskId>/executions` |
| Task lookup by name | `GET /orchestration/executables/tasks?name=<prefix>&environmentId=<envUuid>` (name = prefix-match) |
| List environments | `GET /orchestration/environments` |

Base URL: `https://api.<region>.cloud.talend.com` where `<region>` ∈ `eu|us|us-west|ap|au`.

Auth: bearer token (Talend Personal Access Token), `Authorization: Bearer <PAT>`. Never commit the PAT — keep it in a per-session env var (`TALEND_PAT`).

## Behaviour gotchas

1. **Multi-engine clusters (uat/prd):** one execution exists per engine — when undeploying, **DELETE all of them**. Single-engine clusters (typically dev/tst) have only one. Probe `GET /executions` first to enumerate.

2. **`bind` without undeploy = no-op.** A running microservice ignores configuration updates per Talend Cloud docs. After binding a new artifact version: undeploy + redeploy is mandatory, otherwise the new bundle never loads.

3. **Port conflict on redeploy** (`"Can't configure server port N"`): the previous execution still holds the port — undeploy the old `executing` execution before redeploying.

4. **Self-healing redeploy.** `POST /processing/executions {executable: <taskId>}` *without* a prior DELETE will, in most cases, transparently undeploy the stale bundle and start the new artifact version. The reverse-proxy never sees a 5xx, new executions appear in the public API within 5–15 s. Verified empirically; not formally documented by Talend.

5. **Long-running microservices vanish from `/executions`** (UAT/PRD): microservices that have been `executing` for weeks/months silently disappear from `GET /processing/executables/tasks/{id}/executions`. `total=0` is therefore **not** equivalent to "not running" on long-lived envs. Reliable detection: HTTP-probe via reverse-proxy (an auth-protected path returning HTTP 401 means the service is alive). The public API has no `lastSeen` / `runtimeStatus` field; no query parameter (`from`, `status`, `limit`, `includeFinished`, `all`) brings the executions back. This is an open question with Talend support.

6. **`POST /processing/executions` returns a deploy receipt ID**, not the running execution's ID. Health-check tooling must snapshot pre/post execution IDs on the task and poll for a new `executing` entry, not look up the receipt directly (that returns 404).

## Tooling

- `tools/tmc_release.py` — full release CLI (`status / genpoms / build / publish / bind / promote / deploy / release`). Auto-discovers TMC IDs from API name + env names; the user never types an ID.
- `tools/tmc_microservice_ops.py` — focused lifecycle wrapper (`list / undeploy / redeploy / cycle`). Hard-limited to dev/tst for destructive ops by default.

## Where to read further

- Full TMC API reference: [`knowledge/tmc/task-management.md`](task-management.md)
- Known bugs and workarounds: [`knowledge/tmc/known-bugs.md`](known-bugs.md)
- End-to-end release runbook: [`knowledge/build-publish/release-runbook.md`](../build-publish/release-runbook.md)
