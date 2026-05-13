# tools/ — Changelog

Behavioural changes of the Python tooling under `tools/`. The wider `cimt-claude-talend` repo doesn't keep a project-level changelog; for skill/agent/knowledge changes use `git log`.

## Notable behaviour landed at initial release

- **`cmd_bind`** wraps a `GET → PUT` of `/run-config` around the task body PUT to work around a Talend Cloud bug: when `artifact.version` actually changes (not a no-op PUT), the server silently sets `microservicePort` on `/run-config` to `null`. The save/restore restores the port regardless. See `knowledge/tmc/known-bugs.md`.
- **`cmd_publish`** passes `-Dcloud.publisher.screenshot=true` so the artifact's job-design screenshot is uploaded with the publish.
- **`cmd_build` / `cmd_publish`** include a third glob fallback `**/<api_name>_*/pom.xml` for the case where the parent directory name differs from the artifact name.
- **Post-deploy health check.** `POST /processing/executions` returns a *deploy receipt* ID, not the actual `executing` instance — health-check tooling snapshots execution IDs pre- and post-deploy and polls for a new `executing` entry, rather than looking up the receipt directly (which 404s).
- **Long-running microservices on UAT/PRD.** `GET /processing/executables/tasks/{id}/executions` silently drops microservices that have been `executing` for weeks/months. HTTP probing via reverse-proxy is the reliable detection method. See `knowledge/tmc/known-bugs.md`.
- **Self-healing redeploy.** `POST /processing/executions {executable: <taskId>}` without prior DELETE will undeploy a stale bundle and start the new artifact version automatically.
