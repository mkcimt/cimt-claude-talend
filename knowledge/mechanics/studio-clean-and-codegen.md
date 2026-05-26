---
layer: 2a
---

# Talend Studio "Clean" and code-generation diagnostics

> Talend Studio has no Eclipse-style **Project → Clean** menu. Forcing a fresh code regeneration after an external `.item` edit is a manual procedure. When code-gen fails, the visible error (`processCode is null`) is usually a follow-up — the root cause sits earlier in the stack, most commonly OOM in the Eclipse JDT formatter.

## Why no Project → Clean

Unlike a standard Eclipse Java project, Talend Studio doesn't build the workspace incrementally with the Eclipse JDT builder — it builds via its own Talend / Maven pipeline. There is no `bin/` directory to wipe, and the Eclipse "Clean Projects" command does nothing useful.

Studio caches generated artefacts in two places under the project workspace:

- `<project>/poms/jobs/<group>/<job_name>/<version>/src/main/java/<package>/<job>.java`
  Generated **Java source** for the job/route. Big file (often MBs). Re-generated on every Build Job.
- `<project>/poms/jobs/.../<version>/target/`
  Maven-managed compile output (`.class`) and assembly artefacts (`.zip`, `.jar`). Re-generated on Maven invocation.

There's no centralised invalidation. Each job's cache lives next to its own POM.

## When you need a forced regenerate

- After editing `.item` files outside Studio (Claude, scripts, search-and-replace tools, manual XML surgery).
- When Studio's behaviour suggests cached state divergence (build succeeds but runtime hits old SQL; rename refactor incomplete; mysterious `processCode is null` after an `.item` edit).
- After a migration or Studio patch level change.
- After a git checkout that swept across many `.item` files.

## How to force a regenerate

### Option 1 — Manual cache wipe (most reliable)

1. **Close Talend Studio.**
2. In a file explorer or shell, delete for the affected job/route:

       <project>/poms/jobs/<group>/<job>/<version>/target/
       <project>/poms/jobs/<group>/<job>/<version>/src/main/java/

   For wider sweeps (the whole `i5xx_apis` group, or all jobs), recurse one level higher and delete each child's `target/` + `src/main/java/`. Don't delete `<job_name>/pom.xml` — Studio regenerates that lazily but ad-hoc regeneration of all POMs is a separate (rare) operation.
3. Start Studio. Repository → right-click job → **Build Job** to trigger fresh generation, or open the job in the editor and switch to the **Code** tab (forces re-gen for that single job).

### Option 2 — Job-by-job via the Code tab

1. Repository → double-click a job to open it in the editor.
2. Below the canvas, switch to the **Code** tab.
3. Studio re-generates `.java` for that single job.

Only useful when the divergence is in one or two specific jobs. Doesn't touch joblets referenced by the job, doesn't touch `target/`.

### Option 3 — Maven CLI

For headless or scripted regen:

    cd <project>/poms/jobs/<group>/<job>/<version>
    mvn clean

Wipes `target/`. **Does not** wipe `src/main/java/` (that's Studio-generated, not Maven-generated). Studio still re-generates `src/main/java/` on next Build Job, so this is partial — combine with manual `src/main/java/` delete if you want a fully clean slate.

### Option 4 — Nuclear: m2-clean on Studio start

In `<TalendStudio>/Talend-Studio-win-x86_64.ini` (or Linux/macOS equivalent), add the JVM arg:

    -Dtalend.studio.m2.clean=true

Next Studio start: wipes Studio's bundled local Maven repository (`<TalendStudio>/configuration/.m2/repository/`). Re-download / re-cache on next build. Very heavy — use only when the Maven cache itself is suspected of corruption. Remove the line after the first clean start, otherwise every start re-wipes.

## Diagnosing the `processCode is null` NPE

The Talend stack trace:

    java.lang.NullPointerException: Cannot invoke "String.getBytes()"
    because "processCode" is null
        at org.talend.designer.runprocess.java.JavaProcessor
            .generateCode(JavaProcessor.java:726)
        at org.talend.designer.runprocess.maven.MavenJavaProcessor
            .generateCode(MavenJavaProcessor.java:95)
        at org.talend.esb.standalone.microservice.maven.runprocess
            .StandaloneMicroServiceJavaProcessor
            .generateCode(StandaloneMicroServiceJavaProcessor.java:120)

is **almost never** the actual error — `processCode` is the generated Java content, and it becomes null when an upstream step in the same job-build silently failed. **Always look in `<workspace>/.metadata/.log`** for what happened just before the NPE.

Most common upstream root causes:

### A. Eclipse JDT formatter OOM

The most common cause for `processCode == null` on a route that ran fine before. Search the log for `OutOfMemoryError` in or near `DefaultCodeFormatter.format` or `ASTConverter.convert`:

    !MESSAGE ... ERROR ... java.lang.OutOfMemoryError: Java heap space
    ...
    java.util.concurrent.ExecutionException: java.lang.OutOfMemoryError
        at JavaProcessor$1.run(JavaProcessor.java:801)
    Caused by: java.lang.OutOfMemoryError: Java heap space
        at ASTConverter.convert(...)
        at ASTConverter.convert(...)
        ...
        at DefaultCodeFormatter.format(...)
        at DefaultCodeFormatter.prepareFormattedCode(...)
        at DefaultCodeFormatter.parseSourceCode(...)

**Fix path:** the generated `<job>.java` is too large for the formatter's heap.

1. Measure: `wc -l <project>/poms/jobs/.../src/main/java/.../<job>.java`. Anything over ~500k lines is risky at 4 GB heap; over ~1 M lines is reliably OOM.
2. If size came from an intentional schema/component addition, raise heap (`-Xmx8192m` in `Talend-Studio.ini`).
3. If size is structural (heavy joblet inlining), see [`joblet-inlining.md`](joblet-inlining.md) for the Joblet → Job refactoring trade-off.

Note: at 8 GB heap Studio itself also needs the OS to have ≥ 12 GB free RAM. On a 16 GB machine running other applications, even setting `-Xmx8192m` may not actually achieve 8 GB at runtime.

### B. CreateMavenCamelPom NPE

Symptom in log:

    Cannot invoke "java.util.Map.entrySet()" because "processorArgs" is null
        at CreateMavenCamelPom.isBuildAsZip(...)
        at CreateMavenJobPom.generateAssemblyFile(...)

Means an ESB / microservice POM regeneration tried to read project-level processor args that haven't been initialised yet. Usually transient — happens on first Build Job after Studio start before the project model is fully loaded. Fix: close the route, reopen, retry.

### C. Studio bundle reload race

If `processCode is null` appears immediately after editing the project model (renaming a job, changing a schema repository entry) without intervening save / refresh, the Studio model cache is stale. Fix: `F5` on the Repository, then retry.

## When you see `processCode is null` — diagnostic flow

1. Open `<workspace>/.metadata/.log`.
2. Search for the timestamp of the NPE.
3. Look at the **previous** ERROR / WARN entry in the log — that's the real cause.
4. Match to A / B / C above. Apply the targeted fix.
5. If none match, escalate: capture the surrounding ~200 lines of `.metadata/.log` for support.

## Other size limits to watch (different symptoms, same family)

Tracked here for completeness because all four are downstream consequences of generated-code size:

| Limit | Symptom | Root cause |
|---|---|---|
| JDT formatter OOM | `processCode is null` NPE | Generated `.java` too large for heap |
| 64 KB method bytecode | Compile error pointing at one method | Single method generated too large (often: too many tMap conditions / many inlined joblets in one subjob) |
| 65 535 constant-pool entries | Compile error mentioning constant pool | Class file too wide (many columns × many Structs) |
| Talend tMap auto-generation | "tMap output too complex" runtime exception | Many output rows × many input lookups, exponential expression generation |

The first three are JVM-level; the fourth is Talend-specific. All four respond to the same fix family: reduce per-job inlining (Joblet → Job), narrow schemas, split tMaps.

## Cross-references

- [`joblet-inlining.md`](joblet-inlining.md) — why generated `.java` grows so big.
- [`item-editing-programmatic.md`](item-editing-programmatic.md) — `.item` edit pitfalls that produce broken code-gen.
- [`../build-publish/maven-build.md`](../build-publish/maven-build.md) — Maven-side build mechanics.
