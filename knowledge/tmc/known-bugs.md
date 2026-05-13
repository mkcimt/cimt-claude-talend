# TMC Known Bugs and Workarounds

Empirically verified against Qlik Talend Cloud 8.0.1 R2025-12 (EU region). Each entry: symptom — root cause — workaround.

## `cmd_bind` nulls `microservicePort` on real version bumps

**Symptom.** After `PUT /orchestration/executables/tasks/{id}` with a changed `artifact.version`, the task's `/run-config` sub-resource is silently mutated: `microservicePort` becomes `null`. Subsequent redeploy binds the microservice to a random port. The reverse-proxy can't route traffic → 404 from outside.

**Root cause.** Specific to the direct `PUT /tasks/{id}` codepath when `artifact.version` actually changes. No-op binds (same version) are unaffected. Server-side promotion (`cmd_promote`) preserves `run-config` correctly — only direct binds are broken.

**Workaround** (implemented in `tools/tmc_release.py` `cmd_bind`):

1. `GET /orchestration/executables/tasks/{id}/run-config` → save the body
2. `PUT /orchestration/executables/tasks/{id}` with the new artifact version
3. `PUT /orchestration/executables/tasks/{id}/run-config` with the saved body

Earlier hypothesis ("bind doesn't touch run-config at all") was wrong — only true for no-op PUTs.

**Status.** Talend support ticket draft prepared. The workaround is stable; the wider fix is gating a refactor in `tmc_release.py`.

---

## `cmd_promote` does not propagate `run-config`

**Symptom.** Server-side TMC promotion (`POST /orchestration/promotions`) copies artifact + task body into the target environment but does **not** copy the `run-config` sub-resource. Promoted target tasks land with empty `run-config` → port "auto" → microservice binds to a random port → 404.

**Root cause.** `/run-config` is a separate sub-resource at `/orchestration/executables/tasks/{id}/run-config` containing `microservicePort`, `runtime` (engine + run-profile ID), `deploymentStrategy`, etc. The promotion endpoint does not include it.

**Workaround.**

1. `bind + promote + deploy` via the standard release script
2. Manually `PUT /orchestration/executables/tasks/{targetId}/run-config` with the correct port + run-profile (or set it in the TMC UI)
3. Redeploy

**Status.** Tracked as "tmc_release.py promote loses run-config" in project refactoring backlogs. Per-API port + run-profile-ID tables should live in `tools/<project>/` or project Layer-3 docs.

---

## `executions` retention silently drops long-running microservices

**Symptom.** On long-lived environments (UAT/PRD), microservices that have been `executing` for weeks/months silently disappear from `GET /processing/executables/tasks/{id}/executions`. The API returns `total=0` even though the service is demonstrably alive (SSH/reverse-proxy probe confirms).

**Root cause.** Suspected retention/filter in the TMC public API. No query parameter (`from`, `status`, `limit`, `includeFinished`, `all`) restores visibility.

**Workaround.** Use HTTP probing via the reverse-proxy (any auth-protected route returning HTTP 401 = "service is up"). TMC UI's "Run History" tab also still shows the entry, so this is purely a public-API gap.

**Status.** Open question with Talend support.

---

## `POST /processing/executions` returns a deploy receipt, not an execution ID

**Symptom.** After `POST /processing/executions {executable: <taskId>}`, the returned ID looks like an execution ID but `GET /processing/executions/<id>` returns 404.

**Root cause.** The returned ID is a **deploy receipt**, not the actual `executing` instance. The real execution appears under `/processing/executables/tasks/{id}/executions` with a different ID, typically within 5–15 s.

**Workaround.** Health-check tooling must snapshot execution IDs on the task pre- and post-deploy and poll for a *new* `executing` entry — not look up the receipt directly.

---

## Maven `talendcsv:1.1.0` POM missing from Talend update repo

**Symptom.** Maven build fails with `Could not find artifact org.talendforge:talendcsv:pom:1.1.0`.

**Root cause.** The POM is missing from the Talend update repo; the JAR is present.

**Workaround.** Create a stub POM in the local `~/.m2/repository/org/talendforge/talendcsv/1.1.0/talendcsv-1.1.0.pom` containing a minimal `<project>` declaration with matching groupId/artifactId/version. Rebuild.

---

## `find_api_pom` fails for nested artifact paths

**Symptom.** `tmc_release.py cmd_build` / `cmd_publish` fails with "Could not locate pom.xml" when the artifact's parent directory name differs from the artifact name (e.g. artifact `i5xx_api_<resource>` lives under `i5xx_<resource>/`).

**Fix.** Resolved 2026-05-09 — added a third glob fallback `**/<api_name>_*/pom.xml` to `find_api_pom`. No user action required if `tmc_release.py` ≥ 2026-05-09.

---

## `JobScreenshot: false` in publish output

**Symptom.** Published artifacts in TMC have no job-design screenshot.

**Fix.** Resolved 2026-05-09 — `cmd_publish` now passes `-Dcloud.publisher.screenshot=true`. No user action required if `tmc_release.py` ≥ 2026-05-09.
