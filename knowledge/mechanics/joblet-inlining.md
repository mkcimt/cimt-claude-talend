---
layer: 2a
---

# Joblet inlining and generated-code explosion

> Talend joblets are inlined templates, not function calls — every caller invocation embeds the full joblet code plus a fresh set of Struct classes. This can produce 30+ MB generated `.java` files for large routes and break the Eclipse JDT code formatter at default heap.

## The mechanic

A `JobletProcess` (`<model:JobletProcess>` in the `.item` XML) behaves at code-gen time like a textual macro:

- Studio walks every place a joblet is dropped onto a canvas and **expands the entire joblet content into the calling job's generated `.java`**.
- Each expansion gets its own `..._N_...` prefix on every component name to keep identifiers unique.
- **Every schema in the joblet → one Java `Struct` class per expansion.** A joblet with 18 sub-components (incl. nested sub-joblets) generates 18 Struct classes *per call site*.

There is no function-style deduplication. If a joblet is used 19× in a route, you get 19 copies of every Struct class. A nested joblet inlined into an outer joblet that itself is inlined 19× multiplies further: outer.inline-count × inner.struct-count.

Formula (rough):

    Struct classes generated for a single joblet ≈
        N_invocations_in_calling_route
      × N_components_in_joblet
      × (recursive: N_invocations_of_each_inner_joblet × …)

A single 30-column schema generates a ~50-line block per column → ~2000 lines per Struct class. A heavy auth joblet expanded across many endpoints can produce 300+ Struct classes totalling 800k+ lines.

## Why this matters

### Eclipse JDT formatter OOM

Studio formats every generated `.java` file with the Eclipse JDT code formatter before compilation. The formatter parses the file into an AST and holds it in memory. With:

- ~10 MB generated `.java`: comfortable at default heap (2 GB).
- ~30 MB: tight at 4 GB; may OOM if other Eclipse internals are loaded.
- ~50+ MB: reliably OOMs even at 8 GB.

When the formatter OOMs, Studio swallows the error and the downstream code path sees `processCode == null`, producing the unhelpful follow-up NPE:

    java.lang.NullPointerException: Cannot invoke "String.getBytes()"
    because "processCode" is null
        at JavaProcessor.generateCode(JavaProcessor.java:726)

The NPE is the symptom; the OOM is the cause. See [`studio-clean-and-codegen.md`](studio-clean-and-codegen.md) for the diagnosis flow.

### 64KB method size limit

Independent of formatting, the JVM caps method bytecode at 64 KB. With many inlined joblets sharing one orchestrating method, this limit gets hit before the formatter does. Symptom is different (compile-time error pointing to a specific method), so it's not confusable with the formatter OOM. Mentioned here only because both are "joblet inlining was the trigger".

### Constant-pool overflow

Each class file holds a constant pool capped at 65 535 entries. Very wide schemas (many columns) × many Structs can blow the pool of the main job class. Again — different symptom (specific compile error), same root cause.

## Detecting at design time

Before committing to a heavy joblet, sanity-check:

    # how many times is joblet X used in a route?
    grep -c 'componentName="<joblet_name>"' <route>.item

    # how many components does the joblet itself contain?
    grep -c 'componentName=' <joblet>.item

    # multiply for a back-of-envelope Struct-class count

A number above ~150 Struct classes for one route is a yellow flag; above 300 is a red flag.

## Trade-off: Joblet vs Job

The structural alternative is a standalone **Job** invoked via `tRunJob` from the parent. Comparison:

| | Joblet | Job (via tRunJob) |
|---|---|---|
| Code-gen | Inlined into caller | Separate `.java`, called by JVM-method |
| Per-call generated size | Full joblet × N | One `.java`, reused |
| Variables | Shares `globalMap` automatically | Must pass parameters / read globals explicitly |
| Performance | No process boundary | Slight overhead (separate JVM frame, but same VM) |
| Reusability | Drag-drop convenient | Slightly more setup |
| Versioning | One file, hard to evolve in parallel | Independent versioning easier |

**When to prefer Job over Joblet:** the same logic is called ≥ 5× from one parent, OR the joblet has ≥ 10 components, OR generated `.java` for the parent route is already trending past 10 MB. Conversion is a one-time refactor — convert each joblet drop into a `tRunJob` referencing the new Job, lift schemas to globalMap / parameters.

## Verified

- 2026-05: a REST route with 19 invocations of an auth-helper joblet (21 components, incl. 2 sub-joblets) → 342 Struct classes for that one joblet alone, total 507 Struct classes, generated `.java` 32 MB / 982 k lines. Eclipse JDT formatter OOM at 4 GB heap → `processCode is null` NPE.
- 2026-05: same project, a joblet with a very wide schema → one Struct with 17 093 lines (~340 columns).

## Cross-references

- [`studio-clean-and-codegen.md`](studio-clean-and-codegen.md) — diagnosing `processCode is null` and forcing regen.
- [`item-editing-programmatic.md`](item-editing-programmatic.md) — adding columns to a heavily-inlined joblet's schema multiplies bloat by the inlining factor — measure before editing.
