# Working with Talend `.item` Files

**`.item` files are the source of truth for what jobs do.** They are EMF-XML files exported by Talend Studio. Read them directly when you need to understand or analyse a job. Do not rely on compiled Java output or external reference docs to describe job logic — those drift.

## How to read an `.item` file

Useful tags / structures:

- `<context name="dev|tst|uat|prd">` — context variables per environment
- `<node componentName="...">` — a Talend component (e.g. `tDBInput`, `tMap`, `tDBOutput`, `tJobInstanceStart`)
- `<elementParameter name="UNIQUE_NAME">` — the component's unique ID inside the job (e.g. `tMap_9`)
- `<elementParameter name="QUERY">` — the SQL query of a `tDBInput` / `tDBOutput`
- `<connection>` — flow between two components (Main row, Lookup row, OnSubjobOk, OnComponentOk, Reject, etc.)
- `<nodeData xsi:type="TalendMapper:MapperData">` — the contents of a `tMap` (input tables, output tables, var section, expressions, join keys, filters)
- `<subjob>` — visual subjob grouping (helps understand phases)

For large `.item` files (tens of thousands of lines), prefer `Grep` over reading the whole file. Anchor searches on `UNIQUE_NAME`, component names, or query fragments.

## Picking the right `.item` file

Multiple traps to avoid:

1. **Old / unused jobs may still exist** in `process/` or `routes/` folders. Verify a job is actually in use by tracing call chains (look for `tRunJob` references to it) or via the TMC plan / dispatcher logic.
2. **Multiple Talend-internal versions** (e.g. `iXXX_..._0.1.item`, `iXXX_..._0.2.item`) may coexist. These are *Talend Studio internal versions*, **not git versions**. Rule: the **highest version number is normally the active one**.
3. **`a__archive` folders** (or similar) under interface folders contain retired jobs — ignore unless explicitly asked.

**When in doubt about which `.item` is correct, ASK before proceeding.** Do not guess.

## Reading tMap XML correctly

A `<mapperTableEntries>` entry without an `expression` attribute is only a problem in an **output** table — in an input table it is a normal column declaration. Before flagging an empty expression, confirm the parent `<mapperTable>` is an output table. Input tables are named after incoming flows/lookups; output tables after outgoing rows.

## tFilter active-flag pitfall

A `<elementParameter name="USE_CONDITIONS">false</elementParameter>` on a `tFilterRow` means the filter expression in the component is **not** active. Always check the active flag *before* commenting on filter conditions; an inactive filter is documentation noise, not behaviour.

## Refer to jobs by name, cite paths separately

In user-facing prose (chat replies, documentation), refer to a job by its **job name only** — `iXXX_records_staging`, no `_0.1.item` suffix. The version is internal Talend metadata that distracts the reader.

The file path inkl. version is a **citation** for verification. Provide it:

- in dedicated citation lines / footnotes after a non-trivial claim, or
- collected in a "Where to look" / source table at the end of an analysis or doc, or
- on direct request ("which file did you read?").

Example body text:
> "The worker job `iXXX_records_staging` writes to the staging table…"

Example citation table at the end:

| Job | File |
|---|---|
| `iXXX_records_staging` | `<project>/process/iXXX_records_import/worker/iXXX_records_staging_0.1.item` |

Same convention for `joblets/`, `routelets/`, `routines/`. The job name is what users care about; the path is for traceability.
