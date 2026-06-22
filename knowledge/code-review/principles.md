# Talend Code Review — Principles and Heuristics

These are the lenses the `talend-code-reviewer` agent applies. Principles first (catch novel issues), heuristics second (fast pattern recognition).

## Severity rubric

- **Blocker** — clearly wrong behaviour, demonstrably reachable in a normal flow (or confirmed bug).
- **Warning** — plausible gap, edge-case risk, or reachability unclear.
- **Nit** — style, naming, dead-but-harmless code.

## General principles (apply first)

### 1. Exhaustiveness

Any Boolean aggregation (`||` / `&&`) over a category of fields, and any switch-like branch over an enum, must cover the full category. Procedure: derive the universe from the data model (DB schema, Swagger, input schema), diff against the expression's references. Anything in the universe absent from the expression without documented reason → **Warning** (or **Blocker** if a normal API call can reach the gap in a typical flow).

*Generic example.* A `Var` OR-chains all "change-indicator" fields from an input row. Enumerate every column of that category in the source table or input schema. A missing field means setting only that field produces wrong behaviour — a caller gets a misleading error or silent no-op.

*Canonical anonymized case study.* An API joblet handling change-request POSTs guarded acceptance with a boolean Var `changeContentExists` that OR-ed eight `new_*` fields. The DB table had nine change-indicator fields; one was omitted from the Var. POSTs setting only that omitted field were rejected with a generic "fill out at least one change request field" validation error — a real, business-reported bug. Pattern: guard expression references a *subset* of a field category that actually carries semantic load. Always enumerate the full category from the schema.

### 2. Symmetry across parallel paths

Create vs. Update, POST vs. PUT, Header vs. Line, Pre-History vs. Post-History — the field-set, permission-set, and validation-set must be congruent unless a documented reason exists. Diff symmetric joblets explicitly. Asymmetry without justification → **Warning**.

### 3. End-to-end coherence

Every documented input (Swagger field, file column, request param) must reach a downstream effect (DB write, response field, side effect). Conversely, every effect must trace back to a documented input. Drift in either direction → **Warning** (missing effect = code/doc mismatch; undocumented effect = hidden behaviour).

### 4. Guards dominate their targets

Every gate (auth check, validation, permission lookup, state precondition) must dominate **all** terminal nodes it claims to protect. If a tMap has six output tables and only five route through the auth path, the sixth is a bypass → **Blocker**. If a mutation job does not check the record's legal pre-state (e.g. status must be NEW before PATCH) → **Blocker**.

### 5. Dead code is drift

Hard-coded `true`/`false` literals AND-ed/OR-ed into expressions; Vars whose result is not consumed by any output table or globalMap entry; schema columns written to a table but never read; code with "deactivated" / "TODO" / "temporary" / "not yet removed" comments — all drift until proven intentional. Always at least a **Warning**.

## Heuristics — Talend-specific manifestations

### SQL (`tDBInput` / `tDBOutput` / `tELT*`)

- New `SELECT *` → Warning
- New JOIN without an obvious indexed key → Warning
- `LIKE '%...%'` leading wildcard → Warning (no index seek)
- `WHERE` clause removed or weakened → Blocker until justified
- New correlated subquery in `SELECT` list → Warning (N×M lookups)
- Hard-coded literal where a context var was used → Warning
- Context var not defined in all envs (`dev`/`tst`/`uat`/`prd`) → Blocker
- `COMMIT` interval changed → Warning
- `ORDER BY` removed where downstream relies on order → Blocker
- `DELETE` / `UPDATE` without `WHERE` → Blocker

### tMap

- **Lookup model changed** (`Reload at each row` ↔ `Load Once` ↔ `Cached`):
  - Reload → Load Once: Warning (memory grows with lookup cardinality, may OOM)
  - Load Once → Reload: Warning (per-row DB hit, latency explodes)
- Inner ↔ Left join change → Blocker until justified (data loss / row explosion)
- Inner-reject catch removed → Warning (silent data loss)
- New filter expression → check not accidentally narrower; **check `USE_CONDITIONS` is true** (an inactive filter is a no-op, not a behaviour change)
- Var-section expression changed → re-derive what downstream sees
- Output expression changed (casts, trims, null-handling) → Warning, eyeball semantics
- Match model changed (First / All / Unique) → Blocker (duplicate behaviour shifts)

See [`../mechanics/item-file-format.md`](../mechanics/item-file-format.md) for the tMap XML caveats (input vs. output table semantics).

### Schema / Structures

- Column type/length narrowing → Blocker (truncation risk)
- Nullable=true → false → Blocker (existing nulls fail)
- Key flag changed → Warning
- Column removed → Blocker if downstream reads it; grep callers before flagging severity
- Column added without DB default → check matching DDL exists

### Context / Connection

- New context var → must exist in all envs with sensible values
- DB connection ref changed → confirm target env wiring (esp. tst/uat/prd)
- Property file path changed → matches deployment layout?

### Topology / Error handling

- `tDie` / `tWarn` / `tLogCatcher` removed → Warning (silent failures)
- Reject path removed → Warning
- New `tRunJob` → confirm callee exists and signature matches
- `OnSubjobOk` ↔ `OnComponentOk` swap → Warning (subtle ordering change)
- `tFlowToIterate` introduced on a large flow → Warning (per-row overhead)

### Routes (ESB / Camel)

- Endpoint URL/port/path changes → Warning, check ESB properties
- Auth/security removed or weakened → Blocker
- New external dependency → Warning

### Routines (`code/routines/`)

Real Java — apply normal code review: null safety, exception handling, thread safety (routes can be multi-instance).

### Joblets / Routelets

- Signature change (added/removed/renamed input or output schema column) → Blocker until all callers updated. Grep across the project for references before flagging severity.

### Guard / Validation completeness (Principle 1 applied to Talend)

For every `expressionFilter` Boolean guard in a tMap output table:

1. **Enumerate vs. enumerate.** List all fields the expression references. Derive the full category from the input schema / DB table. Diff. Absent fields → Warning (or Blocker if demonstrably reachable). Category cues: common prefix (`new_*`, `old_*`, `request_*`), common suffix (`_changed`, `_flag`), same domain (all booleans from request body, all date fields, all qty fields). Cross-check by reading the DB table or a sibling joblet — if a column shows up there but not in the guard, that is strong evidence.

2. **Create / update symmetry.** `create_*` and `update_*` joblets for the same resource should reference the same change-field set in their guard. Diff them explicitly.

3. **Schema vs. Swagger vs. DB.** Three-way check. In Swagger but not joblet input (documented, ignored). In DB but not Swagger (real but undocumented). In joblet input but not DB (dead field handling).

4. **Hard-coded `false` / `&& false`.** Turns the whole branch off. Always Warning until confirmed intentional.

5. **Auth-check bypass.** If a job has multiple output tables and the auth/permission check is on only some paths, trace whether every terminal node (DB write, file output, response) passes through the check. Bypass → Blocker.

6. **Reject-table without signal.** `<metadata connector="REJECT">` present but no downstream `tDie` / `tWarn` / writer → Warning (silent data loss).

### Naming asymmetry (smell — not a principle)

Error message says CREATE in a PATCH/UPDATE path. Variable named `customer_id` holds an `order_id`. Joblet labelled `*_get_*` does an UPDATE. Fast cues for misaligned reuse — Nit unless logic is provably wrong.
