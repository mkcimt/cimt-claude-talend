# Job Instance Framework (`tJobInstanceStart` / `tJobInstanceEnd`)

A pair of custom components that give every job run a single database-generated id, record the run in two bookkeeping tables, and hand the job the id of its own last successful run. Projects that use it use it almost everywhere — the id becomes the batch id stamped onto written rows, and the "last successful run" value becomes the lower bound of every incremental-load query. Layer 2b: a project either builds on this or it doesn't, and you can tell from the artifacts.

The components are **not Talend built-ins**. They come from a custom component library installed at Studio level; the consuming project's own `components/` folder is typically empty. Anything that builds the project — a developer's Studio, a headless Maven build, CI — needs that library present, otherwise code generation fails on an unknown component. Both components carry a `RELEASE_LABEL_<date>` parameter (e.g. `Release: 8.6 build at: 20230129`) which is the library build, not the Talend version.

## How to detect this pattern in a project

1. **`grep -rl 'componentName="tJobInstanceStart"' process/`**. Presence anywhere means the pattern is in use; expect it in the large majority of job items, with the remainder being archived, test, or fragment jobs.
2. **A fixed pre-job chain**: `tPrejob` → a connection component → `tJobInstanceStart` → (optional auth/keystore setup) → the connection the job actually works with.
3. **Two table names in the component's parameters**: `TABLE_NAME = "JOB_INSTANCE_STATUS"` and `TABLE_NAME_COUNTER = "JOB_INSTANCE_COUNTERS"`.
4. **globalMap keys** of the form `tJobInstanceStart_1_JOB_INSTANCE_ID`, `_PREV_JOB_INSTANCE_ID`, `_JOB_START_DATE` used in tMap expressions, `tRunJob` context parameters, and inline SQL.
5. **Meta columns** `META_BATCH_ID` / `META_LOAD_DATETIME` on the tables the project writes. These are the id and the run start time; see [`dynamic-scd-framework.md`](dynamic-scd-framework.md) and [`scd-dispatcher-worker.md`](scd-dispatcher-worker.md) for the historisation patterns built on top of them.

(1) alone is conclusive. (4) and (5) tell you how deeply the project depends on it.

## The skeleton

```
tPrejob ──OnComponentOk──▶ tDBConnection (bookkeeping DB)
                                │
                          OnComponentOk
                                ▼
                        tJobInstanceStart   ──▶ INSERT into JOB_INSTANCE_STATUS,
                                │                 SELECT the previous successful run's id
                          OnComponentOk
                                ▼
                        (auth / keystore setup, if the target needs it)
                                │
                          OnComponentOk
                                ▼
                        tDBConnection (data / target system)
```

```
tPostjob ──OnComponentOk──▶ tJobInstanceEnd ──▶ UPDATE the run's row, write the counters,
                                  │                close the bookkeeping connection
                            OnComponentOk
                                  ▼
                          tDBClose (data connection)
                                  │
                            OnComponentOk
                                  ▼
                              tJava (end-of-job log line)
```

**Two connections, closed by different things.** The bookkeeping connection is opened first because `tJobInstanceStart` needs it, and that component is normally configured with `CLOSE_CONNECTION = false` so the connection stays available for the rest of the job (control tables, reference lookups). `tJobInstanceEnd` then runs with `CLOSE_CONNECTION = true` and closes it. The explicit `tDBClose` in the post-job therefore belongs to the **data** connection, not the bookkeeping one. Reading the post-job as "close the bookkeeping DB" is the easy mistake; check the referenced connection component before writing it down.

## The two tables

| Table | Written by | Holds |
|---|---|---|
| `JOB_INSTANCE_STATUS` | `tJobInstanceStart` (insert), `tJobInstanceEnd` (update) | one row per run: job instance id, job name, task name, work item, start and end time, result code and message |
| `JOB_INSTANCE_COUNTERS` | `tJobInstanceEnd` | row counts of the run as named counters, when `SAVE_NAMED_COUNTERS = true` |

The id is database-generated (`IS_AUTO_INCREMENT = true`), so it is **globally monotonic across all jobs**, not a per-job-name sequence. That is what makes `META_BATCH_ID` values comparable between tables written by different jobs, which is in turn what makes the windowing below work across a chain of steps.

The tables can live in the same database as the data or in a separate one — check which connection `tJobInstanceStart`'s `CONNECTION` parameter names. `USE_DATA_SOURCE` / `DATA_SOURCE_ALIAS` are the alternative wiring (a JNDI-style alias resolved at runtime) and are typically `false` / unused when an explicit connection component is present, even though the alias field still carries a leftover value.

## The three published values

| globalMap key | Typical use |
|---|---|
| `tJobInstanceStart_1_JOB_INSTANCE_ID` | stamped into `META_BATCH_ID`; passed down to child jobs as an explicit `tRunJob` context parameter |
| `tJobInstanceStart_1_JOB_START_DATE` | stamped into `META_LOAD_DATETIME`, so every row one run writes carries the identical timestamp |
| `tJobInstanceStart_1_PREV_JOB_INSTANCE_ID` | the lower bound of the incremental-load window, see below |

The id is also mirrored into a context variable via `CONTEXT_VAR_JOB_INSTANCE_ID` (commonly `context.jobInstanceID`), which is how it reaches child jobs when the whole context is transmitted rather than named parameters.

## The windowing idiom

With `RETRIEVE_LAST_RUN_DATA = true` and `RETRIEVE_LAST_RUN_DATA_SUCCESSFUL = true`, the component looks the job up in `JOB_INSTANCE_STATUS` and returns the id of the last run that **finished successfully**. If there is none, the configured `INITIAL_PREV_JOB_INSTANCE_ID` (usually `0l`) applies, so a first run sees everything. Success is defined by `OK_RESULT_CODES` — commonly `"0"`, so any `tDie` exit code counts as failure.

That produces the query shape found all over such projects:

```sql
WHERE META_BATCH_ID >  <PREV_JOB_INSTANCE_ID>   -- last successful run of this job
  AND META_BATCH_ID <= <JOB_INSTANCE_ID>        -- this run
```

Two properties follow, and they answer most "how do we restart this?" questions:

- **A failed run does not move the pointer.** The next run's lower bound is still the last successful id, so everything the failed run did not finish is picked up again. Restart = re-run; there is no pointer to repair.
- **The upper bound is the run's own id.** Rows arriving while the job is running carry a higher id and are left for the next run instead of being half-processed.

## Work items — one job item, several independent pointers

`JOB_WORK_ITEM` is a free-text expression evaluated per run. With `RETRIEVE_LAST_RUN_DATA_FOR_WORKITEM = true`, the last-successful-run lookup is **scoped to that work item**, so a single job item can carry any number of independent pointers.

This is what makes generic helper jobs safe. A shared job called for many source/target pairs sets its work item to something that identifies the pair (e.g. `<source table>:<target table>`); each pair then gets its own window, and a failure on one caller's data does not drag another caller's pointer backwards. Jobs that leave `JOB_WORK_ITEM` empty have exactly one pointer, keyed by job name.

**Audit item:** a job that is called for several distinct targets, uses `PREV_JOB_INSTANCE_ID`, and leaves `JOB_WORK_ITEM` empty is a bug waiting to be noticed. All callers share one pointer, so whichever runs first advances it and the others silently skip their batches. Grep the job for `PREV_JOB_INSTANCE_ID`, then check whether `JOB_WORK_ITEM` distinguishes the callers.

## Parameters worth reading before drawing conclusions

| Parameter | Why it matters |
|---|---|
| `RETRIEVE_LAST_RUN_DATA_SUCCESSFUL` | `false` would make the window start at the last run of any outcome, which changes restart behaviour completely |
| `RETRIEVE_LAST_RUN_DATA_FOR_WORKITEM` | decides whether the pointer is per job or per work item |
| `OK_RESULT_CODES` | defines what counts as a successful run, and therefore what advances the pointer |
| `INITIAL_PREV_*` | the fallbacks on a first run — also what you get after the status table is truncated |
| `CLOSE_CONNECTION` (both components) | see the two-connections note above |
| `CHECK_ALL_COMPONENTS_FINISHED` | `tJobInstanceEnd` waits for all components before closing the row |
| `DO_NOT_SAVE_PASSWORDS` | excludes password-typed context values from what the status row records |
| `SINGLETON_JOB_INSTANCE*` | optional mutual exclusion — the component exposes a `JOB_RUNS_ALONE` return value for an `If` trigger. Not exercised in the project this file was captured from; verify behaviour before relying on it. |

## Trade-offs against the alternatives

- **Versus TMC's own run history.** TMC knows whether a task run succeeded, but the job cannot query that history at runtime, and the id is not available as a value to stamp on rows. The framework's id is usable inside the flow, which is the whole point.
- **Versus a hand-rolled watermark table.** Same idea, but the framework also gives the status row, the counters, and the per-work-item scoping for free, and it fails the run rather than silently continuing if the bookkeeping write fails.
- **Versus source-side timestamp columns.** Comparing `modified_at > last_run_time` depends on clock alignment and on the source maintaining the column. An id assigned by the loading side does not.
- **Cost.** Every job needs the bookkeeping connection open before it can do anything, the component library must be installed everywhere the project is built, and the status table becomes a hot spot that nothing else may truncate — doing so resets every pointer in the project at once.

## Project overlay slot

A consuming project's own `docs/` should record, because none of it is derivable from this file:

- Which connection the bookkeeping tables live behind, and whether that is the same database as the data.
- The project's context-variable prefix families (which prefix means a connection detail, a per-interface parameter, a job parameter, a job-internal working value). See [`context-variables.md`](context-variables.md) for how the values reach the job.
- Which jobs set a work item and what they set it to.
- Whether a downstream step re-stamps `META_BATCH_ID` / `META_LOAD_DATETIME` or carries them over from the previous step — projects differ here, and it decides whether the load timestamp means "entered the chain" or "last touched".
