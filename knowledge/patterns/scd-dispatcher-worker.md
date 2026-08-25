# Parameter-driven SCD dispatcher/worker

A second variant of metadata-driven SCD Type 2 historisation. Same goal as [`dynamic-scd-framework.md`](dynamic-scd-framework.md) — append-only history plus a "current" view — but the generic jobs are **parameterised by the caller** instead of driven by a meta table, and there is no DDL job. Two job items serve every interface and every table in the project. Layer 2b.

Read [`dynamic-scd-framework.md`](dynamic-scd-framework.md) first for the shared concepts (`META_HK` / `META_HV` / `META_BATCH_ID` / `META_LOAD_DATETIME` / `META_DELETION_DATETIME`, tombstones, the LEAD-window current view, the exponential-tombstone failure mode). This file documents only what the parameter-driven variant does differently and the mechanics that are specific to it.

## How to detect this variant

1. **Two generic job items, no meta table.** Names along the lines of `*_dyn_scd_dispatcher` and `*_dyn_scd_worker`, usually under a shared-helper folder. If you find these *without* a `*_META_TABLE_OBJECTS`-style configuration table, you are looking at this variant.
2. **The worker's tMap carries a column of type `id_Dynamic`.** This is the giveaway: the business columns travel as a single dynamic column, which is why one worker can serve any table without knowing a column name.
3. **`tRunJob` calls that pass the table names as context parameters** — source db/schema/table, target db/schema/table, current view, a full-load flag. In the meta-table variant those values come out of a `tFlowToIterate` over the meta table instead.
4. **No view DDL anywhere in the repository.** The current views are created outside Talend. The meta-table variant usually ships a `*_scd_worker_ddl` job; this one does not.
5. **`tHashRow` components in the extract jobs** (see below). The meta-table variant computes the hashes in SQL instead.

## Architecture

```
extract job ──▶ staging table ──▶ *_dyn_scd_dispatcher ──▶ *_dyn_scd_worker ──▶ history table
                                    (once per caller           (once per batch)         │
                                     and table pair)                                    ▼
                                                                              <history>_CURRENT view
```

An interface does not implement historisation at all. It extracts into a staging table and calls the dispatcher — either directly from its control job, or through a thin per-interface wrapper job whose only content is that one `tRunJob`. Wrappers exist so a plan step can carry an interface-specific name; they add no logic.

## Parameters

The dispatcher takes the table coordinates and passes them straight down to the worker, adding the batch id it is currently iterating over.

| Parameter | Meaning |
|---|---|
| source db / schema / table | the staging side to read |
| target db / schema / table | the history table to append to |
| current view | the view exposing the latest version per `META_HK` |
| full-load flag | whether the batch is a complete population, and therefore whether deletion detection may run |
| batch id to process | worker only — the one batch this worker run handles |

Callers fill these from per-interface context values, so which table an interface historises is a configuration change per environment, not a job change. See [`context-variables.md`](context-variables.md) for where those values come from.

## Dispatcher

```sql
SELECT META_BATCH_ID
FROM   <source db>.<source schema>.<source table>
WHERE  META_BATCH_ID >  <PREV_JOB_INSTANCE_ID>
  AND  META_BATCH_ID <= <JOB_INSTANCE_ID>
GROUP BY META_BATCH_ID
ORDER BY META_BATCH_ID ASC
```

`tFlowToIterate` over the result, one `tRunJob` on the worker per id, ascending, with `DIE_ON_CHILD_ERROR` set. Several batches accumulated since the last successful historisation are therefore replayed oldest-first, so the history ends up in chronological order.

**The dispatcher's work item is what makes one shared job safe for many callers.** It is set to the source/target pair (`<source>:<target>`), and with per-work-item last-run lookup each pair gets its own independent window. A failed run on one caller's table pair does not disturb another's. The mechanism is in [`job-instance-framework.md`](job-instance-framework.md); a shared job of this kind that leaves the work item empty is a bug.

## Worker — two subjobs, one transaction

Both subjobs write inside a single transaction, committed after the second one, so a batch is either fully historised or not at all.

### Subjob 1 — new and changed

```
tDBInput  SELECT * FROM <source table> WHERE META_BATCH_ID = <batch id>
              │  (business columns travel as one dynamic column)
              ▼
           tMap ◀── lookup: SELECT META_HK, META_HV FROM <current view>
              │
              ├── inner join on META_HK, filter "META_HV differs"  ──▶ INSERT into <history table>
              ├── inner-join reject (META_HK unknown)              ──▶ INSERT into <history table>
              └── META_HK and META_HV both match  ──▶ dropped
```

Both flows are plain inserts; there is no UPDATE. `META_BATCH_ID` and `META_LOAD_DATETIME` on the inserted rows are the **worker's** own id and start time, not the staging batch's — the history records when a version was historised. The lookup is unfiltered, so a record whose latest version is a tombstone takes part in the comparison like any other; that is deliberate, see the HV mutation below.

### Subjob 2 — deletion detection

Guarded by a `RunIf` on the full-load flag. With a delta load, every record simply absent from the delta would look deleted.

```
tDBInput  SELECT * FROM <current view> WHERE META_DELETION_DATETIME IS NULL
              │
              ▼
           tMap ◀── lookup: SELECT META_HK, META_HV FROM <source table> WHERE META_BATCH_ID = <batch id>
              │
              └── inner-join reject (live, but not in this batch) ──▶ INSERT tombstone into <history table>
```

The tombstone is an ordinary new row: business columns copied from the current version, fresh `META_BATCH_ID` and `META_LOAD_DATETIME`, and `META_DELETION_DATETIME` set to the same timestamp.

Note the explicit `META_DELETION_DATETIME IS NULL` on the input. The current view does not filter tombstones (see below), so without this predicate the subjob would write a fresh tombstone for every already-deleted record on every run — the exponential-growth failure mode described in [`dynamic-scd-framework.md`](dynamic-scd-framework.md), reached by a different route. If you audit this variant, check that predicate first.

### The tombstone's mutated `META_HV`

The tombstone does not copy `META_HV` unchanged. Its first character is replaced:

```java
(row.META_HV != null && row.META_HV.length() > 0) ? "X" + row.META_HV.substring(1) : row.META_HV
```

This is not cosmetic and it is easy to "clean up" by mistake. When a deleted record later reappears in the source **unchanged**, its hash value would otherwise be identical to the tombstone's; subjob 1 would classify it as unchanged, drop it, and the record would stay deleted forever. With the altered value on the tombstone, the reappearing record registers as a change and is inserted as a live version again.

The same effect can be achieved by filtering tombstones out of subjob 1's lookup and treating the record as new — but then the two subjobs read the view with different predicates. Whichever way a project solves it, **check that it is solved**: the resurrect-after-delete path is the one this pattern most often gets wrong.

## Where `META_HK` / `META_HV` come from — `tHashRow`

In this variant the hashes are computed in the **extract** job, by a pair of `tHashRow` components between the tMap and the insert into staging:

```
… ──▶ tMap ──▶ tHashRow (writes META_HK) ──▶ tHashRow (writes META_HV) ──▶ tDBOutput (staging)
```

One component per column. Each names the column it produces in `OUTPUT_COLUMN` and carries a `USE` flag per input column: the key columns for `META_HK`, all business columns for `META_HV`, with the `META_*` columns themselves always excluded so neither hash depends on the batch id or the load timestamp. Everything else is uniform in a well-kept project — `HASH_TYPE = MD5`, `HASH_OUTPUT_ENCODING = HEX`, and a `DELIMITER` between the concatenated values.

**Check the delimiter.** It is what keeps `("AB","C")` and `("A","BC")` apart; the collision risk flagged for the SQL-side hashing in [`dynamic-scd-framework.md`](dynamic-scd-framework.md) applies here identically if it is empty. Also worth a look: `NULL_REPLACEMENT` (projects sometimes mix `""` and a sentinel string across jobs — two jobs hashing the same record with different null handling produce different keys) and `HASH_TYPE` outliers (one `SHA1` among a few hundred `MD5` components is a copy-paste accident, and it silently breaks matching for that table).

Consequence for reading the code: the extract job's tMap leaves `META_HK` and `META_HV` **without an expression**, because they are filled downstream. Do not conclude from the empty tMap cells that the hashes come from the database. `tHashRow` is a custom component from the same library as the job-instance components; see [`job-instance-framework.md`](job-instance-framework.md).

## The current view

Created outside Talend, from one statement per history table:

```sql
create or replace view <schema>.<history_table>_CURRENT as (
select *
from (
    select *,
           lead(META_LOAD_DATETIME, 1) over (partition by META_HK order by META_LOAD_DATETIME) as META_NEXT_LOAD_DATETIME
    from <history_table>) scd
where scd.META_NEXT_LOAD_DATETIME is null);
```

This is "Flavour 1" of [`dynamic-scd-framework.md`](dynamic-scd-framework.md): the version without a successor survives, one row per `META_HK`, and **tombstones are not filtered out**. One row per key is not one *live* row per key — where a record's latest version is a tombstone, the tombstone is what the view returns. Older tombstones, for records deleted and later reappeared, are superseded versions and drop out like any other.

Two things to carry into a review:

- **Consumers must filter tombstones themselves.** Reading the view alone is not "what exists today". Any downstream job, report or DQ check that treats the view as the live population is wrong by exactly the set of currently-deleted records.
- **One row per key assumes `META_LOAD_DATETIME` is unique within a key.** Every row a worker run writes carries that run's start time, so a staging batch containing the same `META_HK` twice puts two versions into the partition with identical load times, and which one the view returns is arbitrary. Projects that hit this add explicit de-duplication in the extract job; if you see a "duplicates" flow there, this is why.

## Audit checklist

1. **Subjob 2's `META_DELETION_DATETIME IS NULL` predicate** — missing it means tombstone growth on every run.
2. **The resurrect-after-delete path** — the mutated tombstone `META_HV`, or an equivalent.
3. **The dispatcher's work item** — must distinguish the source/target pairs it is called for.
4. **The full-load flag per caller** — deletion detection running against a delta load tombstones the entire population minus the delta.
5. **`tHashRow` consistency** — same hash type, encoding, delimiter and null replacement everywhere a given table's hashes are produced.
6. **Duplicate `META_HK` within a batch** — silently non-deterministic in the current view.
7. **Indexes / clustering on the history table** for `(META_HK, META_LOAD_DATETIME)` — the LEAD window scans and sorts the whole table on every read without them.

## Trade-offs against the meta-table variant

- **Adding a table** is a caller-side change here (one `tRunJob` with its parameters, or one wrapper job) versus a data change there (one row in the meta table). The meta-table variant wins on adding many similar tables; this one wins on tables that hang off an interface with its own control flow, because the call sits where the rest of that interface's logic is.
- **No DDL job** means the history table and its view are created by hand outside Talend. Nothing goes stale after a key change — but nothing creates the objects either, and forgetting the view produces a failure only at the worker's first lookup.
- **Visibility.** Which tables are historised is answerable with one query against the meta table in the other variant. Here it is spread across the callers, and the honest answer comes from grepping for `tRunJob` calls on the dispatcher.
- **Blast radius is the same.** Both variants funnel every table through one worker job item, so a change there touches everything.

## Project overlay slot

A consuming project's own `docs/` should record:

- The actual job names of the dispatcher and worker, and where the wrapper jobs live.
- Which database flavours are in play — projects often keep a parallel copy of both jobs per flavour (e.g. a `Postgres_`-prefixed pair alongside the main one), and the copies drift.
- Per interface: the staging table, the history table, the view, and whether the caller passes a full load or a delta.
- Where the current views are maintained, since it is not in the repository.
