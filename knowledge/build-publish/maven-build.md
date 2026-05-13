# Publishing Talend API Microservices via Maven

This document describes how to build and publish i5xx API microservices to TMC manually using Maven — without Talend Studio being open. This is the reference procedure until proper CI/CD is in place.

> Companion: [tmc-task-management.md](tmc-task-management.md) covers what to do *after* publish — binding tasks to new artifact versions, promoting between environments, triggering runs.

## Background

Each i5xx API is a Talend Data Service microservice. Talend Studio normally handles the full build-and-publish cycle through its GUI. When Studio is unavailable or CI/CD isn't set up yet, the same result can be achieved directly via two Maven plugins:

- `org.talend.ci:builder-maven-plugin` — generates/regenerates project POMs and Java source
- `org.talend.ci:cloudpublisher-maven-plugin:8.0.13` — uploads the built ZIP artifact to TMC

Both plugins are already cached in the Studio-local Maven repository at `${TALEND_STUDIO_PATH}/configuration/.m2/repository`.

### Maven settings and repo

Always pass these flags on every Maven command for this project:

```
-s "${TALEND_STUDIO_PATH}/configuration/maven_user_settings.xml"
-Dmaven.repo.local="${TALEND_STUDIO_PATH}/configuration/.m2/repository"
```

---

## Known issue: missing `ContextProperties.java` / `PropertiesWithType.java`

Talend Studio's "Build Job" / "Run Job" writes the main `<JobName>.java` to `poms/jobs/.../src/main/java/<package>/` but **does not** write the two helper classes `ContextProperties.java` and `PropertiesWithType.java` that the main source references. Without them `mvn compile` fails with:

```
ContextProperties cannot be resolved to a type
PropertiesWithType cannot be resolved to a type
```

**Root cause:** The files are generated into the `src/main/java/<package>/` folder only during a full Studio export/build, not on every save.

**Fix:** Create both files manually. See section below.

### Which APIs are affected

Check which APIs are missing the files:

```powershell
Get-ChildItem -Recurse -Path "<TALEND_PROJECT>\poms\jobs\process\i5xx_apis" -Filter "ContextProperties.java" |
  Select-Object FullName
```

Any API directory **not** listed is missing both files and will fail to compile.

### Fix: run the generation script

A Python script in the repo generates both files for all APIs (or a specific one) by parsing the `.item` file:

```powershell
# All APIs at once:
python scripts/generate_context_classes.py

# Only one API:
python scripts/generate_context_classes.py --api i510

# See what would be written without touching files:
python scripts/generate_context_classes.py --dry-run

# Overwrite existing files (e.g. after context vars changed):
python scripts/generate_context_classes.py --api i510 --force
```

The script reads `${TALEND_PROJECT_NAME}/process/i5xx_apis/<api>/*.item`, extracts all `<contextParameter>` elements, and writes the Java files to the correct `src/main/java/` location under `poms/`. No Studio, no server required.

The files stay gitignored (under `poms/`). Re-run the script every time Studio rebuilds a job, because Studio clears the package directory.

---

## Step-by-step: build and publish a single API

Working directory for all commands: the API's versioned POM folder, e.g.  
`${TALEND_PROJECT_NAME}/poms/jobs/process/i5xx_apis/<interface>/<interface>_<artifact>_<version>/`

### 0. Ensure Studio has generated the main source

The main `<JobName>.java` under `src/main/java/<package>/` must be non-empty. If it is 0 bytes (or the file or POM is missing entirely), Studio has never produced the source for this job in this workspace. Open Studio, right-click the job → **Build Job…**, complete the export dialog. This writes the proper `pom.xml` and `<JobName>.java`.

> **Note:** Studio's "Project Settings → Build → Maven → Force full re-synchronize POMs" only writes the `pom.xml` files, **not** the main Java source. Per-job "Build Job" is required (or all jobs once via a sweep).

### 1. Generate `ContextProperties.java` and `PropertiesWithType.java`

Studio does not write these — see section above. Run the script every time after a Studio "Build Job", because Studio clears the package directory and rewrites only the main source:

### 2. Build

```powershell
mvn clean package `
  -s "${TALEND_STUDIO_PATH}/configuration/maven_user_settings.xml" `
  -Dmaven.repo.local="${TALEND_STUDIO_PATH}/configuration/.m2/repository"
```

Expected output: `BUILD SUCCESS`, artifact at `target/<artifactId>_<version>.zip`.

### 3. Publish to TMC

```powershell
mvn org.talend.ci:cloudpublisher-maven-plugin:8.0.13:publish `
  -s "${TALEND_STUDIO_PATH}/configuration/maven_user_settings.xml" `
  -Dmaven.repo.local="${TALEND_STUDIO_PATH}/configuration/.m2/repository" `
  -Dservice.url="https://tmc.eu.cloud.talend.com/inventory/" `
  -Dcloud.token="<PAT_TOKEN>" `
  -Dcloud.publisher.workspace="<your-workspace>" `
  -Dcloud.publisher.environment="dev"
```

> **Note on property names:** The plugin maps CLI `-D` properties to its parameters via different names than the parameter names themselves. Use exactly the names above — `service.url`, `cloud.token`, `cloud.publisher.workspace`, `cloud.publisher.environment`.

> **Note on URL:** The `service.url` must end with `/inventory/`. Without this suffix, the API returns HTTP 301 and the publish fails.

Expected output includes:
```
[INFO] The latest published version is: X.Y.Z
[INFO] Publish version: X.Y.(Z+1)
[INFO] BUILD SUCCESS
```

The log also prints the direct TMC management URL for the published artifact.

---

## TMC connection details

| Parameter | Value |
|---|---|
| `service.url` | `https://tmc.eu.cloud.talend.com/inventory/` |
| `cloud.publisher.workspace` | `<your-workspace>` |
| `cloud.publisher.environment` | `dev` (for dev deploys) |
| PAT token | Stored in the user's password manager — do not commit to repo |

---

## POM layout convention

API microservices typically live under `${TALEND_PROJECT_NAME}/poms/jobs/process/i5xx_apis/<interface>/<artifact>/`. The versioned POM subfolder name matches the `.item` filename (without `.item`). Maintain a per-project inventory in your project's own docs if you need a list.

> **Tip:** Always run `mvn clean package`, not just `package`. Stale `target/` artifacts from a previous successful build can mask current source issues.

---

## TODO

### CI/CD investigation

Goal: replace per-job Studio clicks with a fully automated pipeline based on `builder-maven-plugin:generateAllPoms` + `cloudpublisher-maven-plugin:publish`.

#### Reference (Qlik official docs, 8.0)

- [CI builder-related Maven parameters](https://help.qlik.com/talend/en-US/software-dev-lifecycle-best-practices-guide/8.0/cibuilder-maven-build-options)
- [Generating POM files for your projects](https://help.qlik.com/talend/en-US/software-dev-lifecycle-best-practices-guide/8.0/regenerate-pom-files)

Key facts (verified against Qlik docs, 2026):

| Parameter | Status |
|---|---|
| `-Dlicense.path` | **Only strictly required parameter.** |
| `-Dtalend.studio.p2.base` | **Deprecated since 8.0.1 R2024-05** — no longer supported. Do not pass. |
| `-Dtalend.studio.p2.update` | **Still active and typically required.** Per Qlik docs: *"If you want to migrate your projects to a newer version, you need to install patches, including Talend Studio monthly updates, manual patches, and component patches, using this parameter at build time."* The URL must point at the monthly-update site that matches your Studio's patch level (e.g. `R2025-12`); set `p2UpdateUrl` in your `talend.config.json`. The CLI flag is what brings the auto-downloaded headless CommandLine in sync with Studio. Example: `-Dtalend.studio.p2.update=https://update.talend.com/Studio/8/updates/latest`. |
| `-Dproduct.path` | Optional from CI Builder 8.0.4+. CommandLine is auto-downloaded ("zero install"), default location `${user.home}/.installation/.commandline_8`. |
| `-Dgeneration.type=local` | Server mode is no longer supported — `local` is the only valid value. |
| `-Dinstaller.clean=true` | Optional, forces clean re-install of the headless CommandLine. |

Recommended minimal command (subject to verification once it actually runs end-to-end):

```bash
mvn org.talend.ci:builder-maven-plugin:8.0.27:generateAllPoms \
  -s "<studio>/configuration/maven_user_settings.xml" \
  -Dmaven.repo.local="<studio>/configuration/.m2/repository" \
  -Dlicense.path="<studio>/license" \
  -Dtalend.studio.p2.update="<your-talend-studio-p2-update-url>" \
  -Dgeneration.type=local
```

#### Status

**macOS, 2026-05-07: end-to-end build of an i5xx API works fully headless.** Verified for `i5xx_api_example_1.0` — `target/i5xx_api_example_1_0.zip` is produced cleanly, ready for `cloudpublisher-maven-plugin:publish`. No Studio "Build Job" step needed for that API. `ContextProperties.java` / `PropertiesWithType.java` and `src/main/assemblies/assembly.xml` are all generated by the headless CommandLine when correctly configured — the Python `generate_context_classes.py` helper is no longer required for this flow.

**Two pieces of configuration were the missing link** (not documented in Qlik official docs as far as we could find):

1. **Custom components folder** — the project uses custom components (`tContextInput`, `tFileExcel*`, etc.) that live under `<studio>/user-components/`. The headless CommandLine reads its workspace metadata from `<project-root>/.metadata/`, not from Studio's workspace. Set `USER_COMPONENTS_FOLDER` in the workspace metadata file:

   ```
   <project-root>/.metadata/.plugins/org.eclipse.core.runtime/.settings/org.talend.designer.codegen.prefs
   ```

   Add the line:

   ```properties
   USER_COMPONENTS_FOLDER=${TALEND_STUDIO_PATH}/user-components
   ```

   Without this, joblets that wrap custom components (e.g. `joblet_context_input` wrapping `tContextInput`) fail to load and every API that uses them errors out with `One or more components are missing: tContextInput`.

2. **`-Dstudio.error.on.component.missing=false`** — many real Talend projects carry legacy job/joblet versions that reference renamed or deleted joblets (typos, language changes, retired helpers). Studio tolerates these stale references for old, unused versions; the headless CommandLine is stricter and errors out. This flag turns those into warnings so the build of the *active* versions succeeds.

**Windows comparison:** the earlier `Can't connect to Commandline server : localhost:8002` error on Windows is OS-specific (Java loopback handling) — Mac never hit it. To fix Windows: most likely the same auto-download path (`~/.installation/.commandline_8`) needs to succeed once locally; investigate whether the CommandLine bootstrap was failing because of a proxy / firewall step before reaching p2.

#### Recommended commands (verified on macOS 2026-05-07)

Generate all POMs:

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

Build a single API end-to-end (run from `${TALEND_PROJECT_NAME}/poms/`):

```bash
mvn clean package \
  -s "${TALEND_STUDIO_PATH}/configuration/maven_user_settings.xml" \
  -Dmaven.repo.local="${TALEND_STUDIO_PATH}/configuration/.m2/repository" \
  -Dlicense.path="${TALEND_STUDIO_PATH}/license" \
  -Dtalend.studio.p2.update="${P2_UPDATE_URL}" \
  -Dgeneration.type=local \
  -Dstudio.error.on.component.missing=false \
  -pl jobs/process/i5xx_apis/i5xx_api_example/i5xx_api_example_1.0 -am -fae
```

#### Open follow-ups

1. **Windows root cause** — try the same flow with the auto-downloaded CommandLine on Windows; check if proxy / IPv6 / firewall blocks the p2 download or the local Eclipse loopback during CommandLine startup.
2. **CI/CD pipeline integration** — wire the verified flow into `azure-pipelines.yml` (drop the legacy `sample_pom.xml` secure file, replace `8.0.12` with `8.0.27`, add the `USER_COMPONENTS_FOLDER` workspace pref via a setup step or commit the `.metadata` skeleton, drop the deprecated `-Dtalend.studio.p2.base`).
3. **Custom-component packaging for CI** — currently the components live under the developer's Studio install. For the Azure agent, decide how to provision them (commit into the repo? separate `talend-components` repo? bundled with a custom CommandLine image?).

#### Local prerequisites (macOS)

- JDK 17 (Studio-bundled Zulu): `${JAVA_HOME}`
- Maven 3.9 (`brew install maven`)
- Set `JAVA_HOME` to the Zulu path before invoking `mvn`.
