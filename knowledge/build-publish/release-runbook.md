# Releasing a single API end-to-end

Cookbook for the workflow: code change → publish to dev → deploy on dev → promote to next env → deploy there. One interface at a time.

This is the **default workflow** until a real CI/CD pipeline lives in `azure-pipelines.yml`. For mass operations across many APIs, see [api-maven-publish.md](api-maven-publish.md) and improvise — but that's the exception.

The example here uses `i5xx_api_example`. Substitute the interface ID and the relative POM path for any other API; the inventory lives at the bottom of [api-maven-publish.md](api-maven-publish.md).

## Prereqs (one-time)

- Maven 3.9+ available in PATH (`brew install maven`).
- `JAVA_HOME` pointing to Studio's bundled JDK 17:
  ```bash
  export JAVA_HOME=${JAVA_HOME}
  export PATH="$JAVA_HOME/bin:$PATH"
  ```
- The TMC PAT in the shell env, **never written to disk**:
  ```bash
  export TALEND_PAT="<paste from password manager>"
  ```
- `${PROJECT_ROOT}/.metadata/.plugins/org.eclipse.core.runtime/.settings/org.talend.designer.codegen.prefs` contains `USER_COMPONENTS_FOLDER=${TALEND_STUDIO_PATH}/user-components` — without this the build can't find `tContextInput`. See [api-maven-publish.md](api-maven-publish.md).
- `~/.installation/.commandline_8/` exists (auto-downloaded on first `generateAllPoms` run).

## Step 0 — code change

Edit the `.item` files as needed. The PostToolUse hook in `${PROJECT_ROOT}/.claude/settings.local.json` automatically touches the matching `.properties` file (so TMC's `repository.commit.id` reflects the actual change). See [item-properties-touch.md](../conventions/item-properties-touch.md).

Commit. Direct commits to `master` are blocked — work on a feature branch and open a PR.

## Step 1 — generate POMs (only when items changed structurally)

If you only edited expressions/values inside an existing `.item`, you can skip this and reuse the existing POMs.
If you added/renamed jobs or joblets, regenerate from the project root:

```bash
mvn org.talend.ci:builder-maven-plugin:8.0.27:generateAllPoms \
  -s "${TALEND_STUDIO_PATH}/configuration/maven_user_settings.xml" \
  -Dmaven.repo.local="${TALEND_STUDIO_PATH}/configuration/.m2/repository" \
  -Dlicense.path="${TALEND_STUDIO_PATH}/license" \
  -Dtalend.studio.p2.update="${P2_UPDATE_URL}" \
  -Dgeneration.type=local \
  -Dstudio.error.on.component.missing=false \
  -N
```

`generateAllPoms` rewrites every job's `pom.xml` from scratch, including resetting the `<version>` to the Talend item version (e.g. `1.0.0`). If you want a different artifact version (rare — TMC normally auto-increments the patch from the last published version), edit it before Step 2.

## Step 2 — build the single API

From `${PROJECT_ROOT}/${TALEND_PROJECT_NAME}/poms/`:

```bash
API=jobs/process/i5xx_apis/i5xx_api_example/i5xx_api_example_1.0

mvn clean package \
  -s "${TALEND_STUDIO_PATH}/configuration/maven_user_settings.xml" \
  -Dmaven.repo.local="${TALEND_STUDIO_PATH}/configuration/.m2/repository" \
  -Dlicense.path="${TALEND_STUDIO_PATH}/license" \
  -Dtalend.studio.p2.update="${P2_UPDATE_URL}" \
  -Dgeneration.type=local \
  -Dstudio.error.on.component.missing=false \
  -pl "$API" -am -fae
```

Expected output: `BUILD SUCCESS`, artifact at `$API/target/<artifactId>_<version>.zip`.

## Step 3 — publish to dev

```bash
mvn org.talend.ci:cloudpublisher-maven-plugin:8.0.13:publish \
  -s "${TALEND_STUDIO_PATH}/configuration/maven_user_settings.xml" \
  -Dmaven.repo.local="${TALEND_STUDIO_PATH}/configuration/.m2/repository" \
  -Dservice.url="https://tmc.eu.cloud.talend.com/inventory/" \
  -Dcloud.token="$TALEND_PAT" \
  -Dcloud.publisher.workspace="<your-workspace>" \
  -Dcloud.publisher.environment="dev" \
  -Dcloud.publisher.screenshot=true \
  -pl "$API"
```

Read the log for `Publish version: X.Y.Z` — that's the new artifact version on dev. Confirm `JobScreenshot: true` in the same log block; without the flag the artifact lands in TMC without its design screenshot.

## Step 4 — bind the dev task to the new version

Inputs you need: just the **API name**. Everything else (artifact ID, workspace ID, dev task ID, fully-qualified latest version) is discovered.

```bash
BASE="https://api.eu.cloud.talend.com"
NAME="i5xx_api_example"

# 1) find the dev artifact for this name → ART_ID + DEV_WS + latest fully-qualified version
read -r ART_ID DEV_WS NEW_VER < <(
  curl -s -H "Authorization: Bearer $TALEND_PAT" -G --data-urlencode "name=$NAME" \
    "$BASE/orchestration/artifacts" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for it in d['items']:
  if it['name']=='$NAME' and it['workspace']['environment']['name']=='dev':
    print(it['id'], it['workspace']['id'], it['versions'][0]); break")
echo "artifact=$ART_ID  workspace=$DEV_WS  version=$NEW_VER"

# 2) find the dev task pinned to that artifact
TASK_ID=$(curl -s -H "Authorization: Bearer $TALEND_PAT" \
  "$BASE/orchestration/executables/tasks?workspaceId=$DEV_WS&artifactId=$ART_ID" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['items'][0]['executable'])")
echo "devTask=$TASK_ID"

# 3) fetch full task, transform GET → PUT body, PUT
curl -s -H "Authorization: Bearer $TALEND_PAT" "$BASE/orchestration/executables/tasks/$TASK_ID" -o /tmp/_t.json
python3 - <<PY > /tmp/_put.json
import json
t=json.load(open('/tmp/_t.json'))
out={k:v for k,v in t.items() if k not in ('workspace','version','id')}
out['workspaceId']=t['workspace']['id']
out['artifact']={'id':t['artifact']['id'],'version':'$NEW_VER'}
print(json.dumps(out))
PY
curl -s -X PUT -H "Authorization: Bearer $TALEND_PAT" -H "Content-Type: application/json" \
  "$BASE/orchestration/executables/tasks/$TASK_ID" -d @/tmp/_put.json \
  | python3 -c "import json,sys;t=json.load(sys.stdin);print('task version', t['version'], 'now bound to', t['artifact']['version'])"
```

> **Why `PUT` and not `PATCH`:** PATCH on the orchestration tasks endpoint does not accept the `artifact` field (HTTP 400 `unrecognized field: artifact`). PUT requires the full task entity — any field omitted is set to null. See [tmc-task-management.md](tmc-task-management.md).

> **Restore `microservicePort` after the PUT.** Talend Cloud silently sets `microservicePort` on `/run-config` to `null` whenever the task PUT actually changes `artifact.version` (no-op PUTs don't trigger it). If you're scripting bind by hand, GET `/orchestration/executables/tasks/$TASK_ID/run-config` *before* the task PUT and PUT the same body back to that sub-resource *after* the task PUT — otherwise the next deploy lands on a random port. `tmc_release.py bind` does this automatically. See [`../tmc/known-bugs.md`](../tmc/known-bugs.md).

## Step 5 — deploy on dev (optional)

If you want the API live on dev right away (rather than waiting for the next scheduled run):

```bash
curl -s -X POST -H "Authorization: Bearer $TALEND_PAT" -H "Content-Type: application/json" \
  "$BASE/processing/executions" -d "{\"executable\":\"$TASK_ID\"}"
# returns {"executionId":"..."}
```

Skip this if you only want dev to receive the artifact in TMC and don't want to interrupt running endpoints (e.g. for a promote-then-deploy-on-target flow).

> **If the previous version is still deployed**, the POST will fail with *"Can't configure server port N"* — the old execution is still holding the port. Undeploy it first via `DELETE /processing/executions/<oldExecutionId>` (note: returns `text/plain`, so use `-H "Accept: text/plain"` or `curl` will be fine without an Accept header). For bulk operations across all i5xx APIs, use [`cimt-talend/scripts/tmc_microservice_ops.py`](../scripts/tmc_microservice_ops.py) (`list`, `undeploy`, `redeploy`, `cycle`). Full lifecycle reference: [tmc-task-management.md → Workflow D](tmc-task-management.md#workflow-d--undeploy--redeploy--cycle-a-microservice-verified-2026-05-08).

## Step 6 — promote to the next environment

Reusable env-pair promotions already exist (`dev to tst`, `tst to uat`, `uat to prd`, etc.). Look up by source/target env names — no IDs to memorise.

```bash
SRC="dev"
DST="tst"

# 1) find the matching env-pair promotion definition
PROM_ID=$(curl -s -H "Authorization: Bearer $TALEND_PAT" \
  "$BASE/orchestration/executables/promotions" \
  | python3 -c "
import json,sys
for p in json.load(sys.stdin):
  if p['sourceEnvironment']['name']=='$SRC' and p['targetEnvironment']['name']=='$DST':
    print(p['executable']); break")
echo "promotion=$PROM_ID"

# 2) execute it for our task; FLOW promotes the task and brings the bound artifact along
PROM_RESP=$(curl -s -X POST -H "Authorization: Bearer $TALEND_PAT" -H "Content-Type: application/json" \
  "$BASE/processing/executions/promotions" \
  -d "{
    \"executable\":\"$PROM_ID\",
    \"advanced\":{\"artifactId\":\"$TASK_ID\",\"artifactType\":\"FLOW\"},
    \"context\":\"$NAME $SRC->$DST $NEW_VER\"
  }")
echo "$PROM_RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin)
er=d.get('executionReport',d)
print('status:', er.get('status'))
for w in er.get('workspaces',[]):
  for f in w.get('flows',[]):
    print('targetTask:', f.get('targetId'), 'name:', f.get('name'))"
TARGET_TASK=$(echo "$PROM_RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin); er=d.get('executionReport',d)
for w in er.get('workspaces',[]):
  for f in w.get('flows',[]):
    if f.get('id')=='$TASK_ID': print(f.get('targetId')); break")
echo "TARGET_TASK=$TARGET_TASK"
```

> Despite the field name, `advanced.artifactId` carries the **task ID** (the dev task) when `artifactType=FLOW`, not the artifact ID. The promotion brings the bound artifact along. See [tmc-task-management.md](tmc-task-management.md).

## Step 7 — deploy on the target env

```bash
curl -s -X POST -H "Authorization: Bearer $TALEND_PAT" -H "Content-Type: application/json" \
  "$BASE/processing/executions" -d "{\"executable\":\"$TARGET_TASK\"}"
```

For onward promotion to uat / prd, repeat Steps 6 + 7 with `SRC=tst DST=uat` etc. The promotion lookup discovers each env-pair by name.

## Sanity check — confirm TMC tracks the right commit

```bash
curl -s -H "Authorization: Bearer $TALEND_PAT" \
  "$BASE/orchestration/artifacts/$ART_ID/versions/$NEW_VER" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);r=d.get('repository',{});c=r.get('commit',{});print('branch:', r.get('branch'));print('commit:', c.get('id'));print('author:', c.get('author'))"

# expected to match `git log -1 --format='%H %ae'`
```

If the commit doesn't match: see [item-properties-touch.md](../conventions/item-properties-touch.md). The `.properties` of the involved item probably wasn't updated before the publish.

## What's still manual / not yet automated

- Detecting *which* APIs need a republish based on the diff in a PR (currently: rebuild whatever you think changed, or all of them).
- Pre-publish smoke tests against dev.
- Auto-update of dev tasks after publish (could be triggered from the publish step).
- Multi-env release plans / approval gates.
- Same workflow for **batch jobs** (`process/i1xx`–`i4xx`) — never proven end-to-end via the headless flow yet.

These are the things the proper Azure Pipelines setup needs to absorb. Until then, this runbook is the source of truth.
