# Context Variable Patterns

Talend offers several mechanisms for resolving runtime configuration. Projects pick one or combine them. This file catalogs the options and explains **how to detect from the project's artifacts** which variant is actually in use — there is no pre-declaration to consult; the code is the source of truth.

## How to detect which variant a project uses

Scan the project once, in this order:

1. **Look for a startup joblet that calls `tContextLoad`**. Common names: `*_startup`, `*_init`, `*_load_context`, or a routine called early in PreJob. Such a joblet means **Pattern B or C** is in use — the values are loaded at runtime from outside the Studio context group, typically `.properties` files.
2. **If you find a `tContextLoad` reading from a fixed external folder structure** (e.g. `<root>/config/<env>/...`, where `<root>` is itself a context variable like `framework_root` or `config_root`), the project uses **Pattern B** (external framework repo). Check the loader path expression to confirm the layout.
3. **If `tContextLoad` reads from a path that's computed dynamically** (built from request data, customer code, or job parameters), the project uses **Pattern C**.
4. **If no `tContextLoad` / no startup-style joblet is found**, the project uses **Pattern A** — values come from Talend Studio's native context groups under `<project>/context/`. Verify by checking that `<project>/context/*.context` files have per-env values populated.
5. **Mixed**: if you see Pattern A *and* `tContextLoad` references (for a subset of variables), it's a hybrid — usually Pattern B handles the bulk while a few values stay Pattern A. Treat as B for documentation and resolution purposes.

In code, all variants resolve via `context.<name>` (typed) or `context.getProperty("<name>")` (string lookup). The presence of `context.getProperty(...)` alone does **not** tell you which variant — it works for all of them.

## Variants

### A — Built-in Talend context groups

Defined in Studio under `<project>/context/`, with one value per environment (`dev`, `tst`, `uat`, `prd`) per variable. At runtime, the active environment is selected via TMC's `--context=<env>` arg or Studio's run profile.

- **Pros**: Native to Talend, no external dependencies, schema-checked in Studio.
- **Cons**: Values live in the repo (or in TMC's job-context override UI). Changing a value requires a Studio commit or a TMC config change. No central place for cross-job sharing beyond context groups.

Resolve in code via `context.<name>` (typed) or `context.getProperty("<name>")` (string lookup, works also for dynamic keys).

### B — External configuration framework repo

A separate git repository (commonly `talend-framework` or similar) checked out **outside** the Studio workspace, structured per environment:

```
<framework-root>/
├── config/{dev,tst,uat,prd}/
│   ├── interfaceConfig/iXXX/iXXX_*.properties     ← per-interface context properties
│   └── projectConfig/<project>/
│       ├── connection.properties
│       └── project.properties                      ← project-wide properties
├── connection/{dev,tst,uat,prd}/*.properties       ← DB / sFTP / mail connection details
└── data/{dev,tst,uat,prd}/iXXX/                    ← runtime data folders (input/output)
```

A job loads its environment's properties at startup (typically through a startup joblet that reads the relevant `*.properties` files into the context group), so `context.getProperty("foo")` resolves against the external file at runtime.

- **Pros**: Config separated from code, central per-env source of truth, edits go through normal git PR flow on the framework repo, easy to roll forward/back without touching the Talend project.
- **Cons**: Two repos to keep in sync. New context vars must be added in both Studio (declaration) and the framework (value).

The local path to the framework checkout is **developer-specific** (`/var/opt/talend/framework_<project>/` is a common convention) and lives in user/laptop config (Layer 4) — not in the Talend project itself.

### C — `tContextLoad` / dynamic loaders

Talend provides components (`tContextLoad`, `tFileInputProperties`, `tFileInputJSON` feeding `tContextLoad`) that explicitly read property files at runtime and update the context. Useful when the property source is not known at design time, when the same job must run against many configurations, or for late-binding feature flags.

- **Pros**: Maximum flexibility, well-suited for multi-tenant or multi-customer batch jobs.
- **Cons**: Without conventions, becomes a "magic" layer that hides where a value comes from. Document the loader location explicitly.

## Looking up `context.getProperty("X")` in docs

When a job references `context.getProperty("foo_bar")` and the value matters for documentation (status codes, customer codes, file paths, mapping-table object types):

- **Pattern A**: open `<project>/context/<group>/dev.properties` (or the relevant context group's files).
- **Pattern B**: open `<framework-root>/config/dev/interfaceConfig/iXXX/iXXX_*.properties` for per-interface keys, or `<framework-root>/config/dev/projectConfig/<project>/project.properties` for project-wide keys.
- **Pattern C**: trace back to the loader component, then to the file path it reads.

Do not embed full property values in documentation unless the value *is* the business rule (e.g. a status enum). For connection details, point at the framework key by name instead.
