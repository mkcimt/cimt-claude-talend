# Touching `.properties` when editing `.item` files via code

When you (Claude or any non-Studio tool) edit a `.item` file directly — refactoring expressions, fixing a tDBConnection property, sweeping joblets — you must also touch the matching `.properties` file. Otherwise downstream systems lose track of the change.

## Why this matters

Talend Studio writes a `.properties` file alongside every `.item`. The `.properties` file is Talend's *metadata* for the item: who created it, when it was last modified, which Studio build wrote it. When Studio edits a job and saves, **both** files are updated. When a code-only edit changes only the `.item`, the `.properties` stays frozen.

Two concrete consequences observed in this project:

1. **TMC `repository.commit.id` goes stale.** When `cloudpublisher-maven-plugin:publish` uploads an artifact to TMC, it records a `repository.commit` field per artifact version. Empirically (verified 2026-05-07 across all 11 i5xx APIs), the recorded commit equals `git log -1 -- <item>_<version>.properties` — the last commit that touched the **`.properties`** file, not the `.item`, not branch HEAD. So an artifact that was actually rebuilt from updated `.item` content shows a commit ID from the last unrelated `.properties` edit (often a mass migration commit like *"R2024-10 upgrade"* or *"R2024 upgrade apis"*). TMC users looking at the artifact metadata can't tell what's actually in it.

2. **Studio's local change-detection / diff views may not surface the edit** when reopened. Studio compares timestamps and version strings as a fast path before falling back to content diff.

## What to update — and what NOT to

### Update on every code-only `.item` edit

In the matching `<item>_<version>.properties`:

- **`modified_date`** — set to the current local ISO 8601 timestamp with timezone (the format Talend writes, e.g. `2026-05-07T18:42:11.000+0200`).
- **`modified_product_version`** — set to the running Studio's full patch string (e.g. `8.0.1.20260102_0846-patch`). Source of truth: the `productVersion` attribute in `${TALEND_PROJECT_NAME}/talend.project`. The kit's helper script (`tools/touch_item_properties.py`) parses it from there automatically.

Both are stored as XML attributes on `<additionalProperties>` elements:

```xml
<additionalProperties xmi:id="..." key="modified_date" value="2026-05-07T18:42:11.000+0200"/>
<additionalProperties xmi:id="..." key="modified_product_version" value="8.0.1.20260102_0846-patch"/>
```

Only the `value` attribute changes. Leave `xmi:id` alone — it's a stable EMF identifier.

### Do NOT touch

- **`item_key`** — verified empirically to be **stable across item versions** (i500's `0.1`, `1.0`, `1.1` all share the same key `e5b981e5…`). It identifies the *logical* item, not the content. Don't recompute, don't change.
- **`version`** attribute on `<TalendProperties:Property>` — that's the Talend item version (`0.1`, `1.0`, `1.1`). Bumping it is a deliberate action ("Edit Properties → Version" in Studio); doing it from outside Studio creates a parallel item-version file pair (`<item>_<new>.item` + `<item>_<new>.properties`) and is not what we want for in-place edits.
- **`id`** on `<TalendProperties:Property>` (e.g. `_pZ2q4JceEe2p8ORJ3vKiZA`) — Talend item ID, stable.
- **`created_date`, `created_product_version`, `import_*`** — historical, never updated.

### When NOT to touch `.properties` at all

If your change to the `.item` is purely cosmetic (whitespace, attribute ordering with no semantic effect, adding a comment somewhere Studio strips on save), prefer not to write at all. Otherwise the diff is noise.

If the edit *does* change behaviour but you also plan to immediately re-open the item in Studio to do something else, just let Studio update the file on save — both edits land in one `.properties` write.

## Workflow

1. Edit the `.item` file as usual.
2. Update the matching `.properties` file's `modified_date` + `modified_product_version` (see above).
3. Commit both files in the same git commit.

A small helper script lives at [`tools/touch_item_properties.py`](../../tools/touch_item_properties.py) that takes one or more `.item` paths and updates the matching `.properties` file in place. Use it from a sweep, e.g.:

```bash
python3 "$CIMT_TALEND_PATTERNS/tools/touch_item_properties.py" <project>/process/i5xx_apis/i5xx_api_example/i5xx_api_example_1.0.item
```

## Protocol for Claude when editing `.item` files

**This is a hard rule, not an optimization.** Every time you (Claude) write to a `.item` file through `Edit`, `MultiEdit`, or `Write`, you must — in the **same turn** — update the sibling `.properties` file's `modified_date` and `modified_product_version` values. Studio takes care of this on its own when a human saves through the UI; for code-only edits there is no Studio in the loop, so you do it.

Two ways to do it; both are acceptable:

**A. Direct edit (works when the `.properties` file is small and the format is clear).** Open the `<item>_<version>.properties`, find the two `<additionalProperties …>` elements, and rewrite the `value` attributes only. `modified_date` to a current ISO 8601 timestamp with timezone (e.g. `2026-05-13T11:42:11.000+0200`); `modified_product_version` to the string from `<TalendProjectName>/talend.project`'s `productVersion` attribute. Leave `xmi:id` alone.

**B. Helper script.** Call the kit's helper, which reads `talend.project` itself and writes both fields correctly. Prefer this whenever you're touching more than one item in a turn, or when you don't want to format the timestamp yourself:

```bash
python3 "$CIMT_TALEND_PATTERNS/tools/touch_item_properties.py" <path-to-item-file>
```

Either way the rule is: **same turn, both files, single commit.** Splitting them across commits is a smell — review tooling will treat the `.item` commit as untracked by TMC.

## Sources / verification

Talend does not publicly document the internal semantics of `.properties` fields beyond what Studio shows in the UI. The findings above are empirical (verified 2026-05-07 against a live Talend project and TMC `eu.cloud.talend.com`):

- All 11 i5xx APIs' TMC-recorded commit on tst (after our 2026-05-07 publish + promote run) matched the last git commit of the corresponding `.properties` file exactly. The cloudpublisher does not look at the `.item` file's git history, branch HEAD, or build-time SHA when populating `repository.commit`.
- `item_key` was identical across all coexisting versioned `.properties` files of the same item.
