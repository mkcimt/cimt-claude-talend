---
layer: 2a
---

# Editing `.item` files programmatically — pitfalls and checklist

> Editing `.item` from outside Studio (scripts, `Edit`/`Write`, `sed`, find-and-replace tools) is convenient for repetitive schema/SQL/contextParameter changes — but the file format has half a dozen invariants Studio never thinks about because its own editor preserves them automatically. Get any of them wrong and Studio either refuses to load the joblet, generates pathological Java, or silently corrupts the project.

## Hard invariants — must hold after every edit

### 1. Line endings on Windows: CRLF

Talend Studio on Windows writes `.item` files with **CRLF** line terminators. The project's surrounding `.item` files all use CRLF. Mixing LF and CRLF across joblets in the same route causes erratic code-gen behaviour (some flows generate normally, others produce duplicated newlines in MEMO_JAVA / MEMO_SQL string literals, blowing up the generated `.java`).

Common mistake: Python `Path.write_text(...)` on Windows writes `\r\n` by default *only if* `newline` is unset — but `Path.read_text` already normalises CRLF to LF on read, so a naive read-modify-write round-trip can silently strip the CRs unless the write is done in binary mode.

**Correct programmatic edit on Windows:**

    # binary read + binary write — preserves CRLF byte-for-byte
    raw = p.read_bytes()
    # do replacement on bytes (or decode → modify → encode), then:
    p.write_bytes(modified)

    # OR explicit text mode with platform newline preservation:
    p.write_text(text, encoding="utf-8", newline="")

Verify after writing:

    file <path/to/file.item>

The line must contain `with CRLF line terminators`. If it doesn't, the file was written wrong.

Note: `core.autocrlf=true` (typical Windows git config) means git STORES `.item` with LF and EXPANDS to CRLF on checkout. So `git show HEAD:<file> | file -` will report no-CRLF — that's the storage form, not the disk form. Always check the file on disk.

### 2. `<elementParameter>` element IDs must be unique within the parent

Inside a `<elementParameter>` block, each `<elementValue elementRef="..." id="N"/>` must have an `id` value unique within that `<elementParameter>`. Studio's code generator iterates by id and indexes some lookups by id; duplicates produce inconsistent code-gen pathways (a missing `equals/hashCode` here, a doubled column reference there).

**Common mistake when cloning blocks:** copying a `<elementValue elementRef="TRACE_COLUMN" value="X" id="3"/>` triple verbatim with the value substituted but the id reused.

**Correct programmatic clone:** bump every numeric `id` in the cloned block by a large offset (e.g. `+1000` or `+2000`) so it doesn't collide with originals. Verify:

    python -c '
    import re, sys
    from collections import Counter
    text = open(sys.argv[1]).read()
    for m in re.finditer(r"<elementParameter[^>]*>(.*?)</elementParameter>", text, re.DOTALL):
        ids = re.findall(r"\bid=\"(\d+)\"", m.group(1))
        dupes = [k for k,v in Counter(ids).items() if v > 1]
        if dupes: print(f"DUPE: {dupes} in {sys.argv[1]}")
    ' <path/to/file.item>

### 3. Encoding: UTF-8 without BOM

`.item` files are XML with `<?xml version="1.0" encoding="UTF-8"?>` and **no byte-order mark**. On Windows, Python's default `open(..., 'w', encoding='utf-8')` writes without BOM (good) but `'utf-8-sig'` adds one (bad). Studio refuses to load a `.item` that starts with `EF BB BF` — the file appears empty in the Repository.

### 4. XML well-formedness with embedded HTML-entity newlines

Many `MEMO_SQL` / `MEMO_JAVA` / `MEMO_EDITOR_JAVA` values contain embedded newlines encoded as `&#xD;&#xA;` (CR+LF) or `&#13;&#10;`. These entities must remain entities — never decode them to literal newlines, because that breaks the single-attribute-value XML structure. When string-replacing inside these values, replicate the surrounding entity sequence verbatim.

### 5. Sibling `.properties` must be touched on every `.item` edit

Studio bumps `modificationDate` and `productVersion` in the `.properties` file on its own saves. Code-only edits must do the same so TMC's `repository.commit.id` tracking treats the change as a real change. Use the kit's helper:

    python $CIMT_TALEND_PATTERNS/tools/touch_item_properties.py <path/to/file.item>

See [`item-properties-touch.md`](item-properties-touch.md).

## Soft conventions — match the project style

### XMI internal IDs

`internalId="_xxxxxxxxxxxxxxxxxxxxxx"` attributes look like Eclipse XMI UUIDs. Studio generates them as 22-character base64-ish strings. New entries you write need **any unique** string in this format — they don't have to be valid UUIDs, just distinct from existing ones in the file. A safe pattern: pick a recognisable prefix (`_Sldew0AAEf...`) and increment per new entry. Don't reuse an existing id.

### Whitespace and indentation

Studio uses tab indentation (4-tab style for nested elements, 2-tab for top-level under `<process>` / `<context>`). When inserting new XML elements, mirror the indentation of the surrounding sibling element. Mismatched indentation is cosmetic only — Studio doesn't care — but produces noisy diffs and confuses code-review.

### Position of inserts

For repeated structures (list of `<contextParameter>`, list of `<column>` in a `<metadata>` block, list of `<elementValue>` inside an `<elementParameter>`), the safest insert position is **immediately after the most-similar existing entry** (e.g. a new permission contextParameter goes after the last existing `permission_*` entry, not at the end of the env-context group where unrelated params live). Mirrors how Studio's UI inserts them.

## Mandatory pre-edit checklist for Claude

Before any tool call that writes a `.item`, complete this checklist. None of these are optional.

- [ ] The file currently has **CRLF** endings (verify with `file <path>`). If not, investigate before writing.
- [ ] The edit will preserve CRLF. If using Python, prefer `read_bytes` / `write_bytes` with byte-level replacement; if using Claude's `Edit` tool on existing CRLF content, line endings are preserved automatically (verify after the edit anyway).
- [ ] If cloning an `<elementValue>` or `<elementParameter>` block that contains numeric `id="N"` attributes, the clone has those ids bumped by a high constant so no duplicate emerges within the parent.
- [ ] Embedded `&#xD;&#xA;` / `&#13;&#10;` / `&#x9;` entities inside string values are preserved verbatim.
- [ ] After writing: re-verify CRLF (`file`), re-verify no duplicate `<elementParameter>`-internal ids, re-verify the XML still parses (`python -c "import xml.etree.ElementTree as ET; ET.parse('<file>')"`).
- [ ] Run `touch_item_properties.py` on the file before committing.

For batch edits across many `.item` files (script-driven), run the same verification across the batch — not just the first file.

## After-edit invariants to spot-check

- [ ] Line ending check via `file` reports CRLF (or matches the project convention).
- [ ] XML parses without error.
- [ ] No duplicate ids within any `<elementParameter>` (`python` snippet above).
- [ ] `git diff <file>` shows only the intended functional change — no whole-file diff caused by line-ending flip.
- [ ] Sibling `.properties` touched (modificationDate, productVersion advanced).

## Why this is in Layer 2a

Every one of these invariants is a Talend Studio mechanic — true for any project using `.item` files, regardless of business domain or framework choice. Each was learned the hard way:

- LF/CRLF flip: in a 2026-05 session, `iXXX_get_record_0.1.item` and 12 siblings written via Python `Path.write_text` ended up as LF on disk while the rest of the project stayed CRLF. The mixed state interacted with another issue (joblet-inlining size) to push the generated `.java` over the formatter's heap limit.
- Duplicate ids: same session, `iXXX_list_records_0.1.item` had `id="3,4,5"` appearing twice in a TRACE_COLUMN list after a naive block-clone with `value` substitution but no id bump.
- BOM: documented in Talend forum threads as a recurring import failure mode.

## Cross-references

- [`item-file-format.md`](item-file-format.md) — what the `.item` XML tags mean (read-direction guide).
- [`item-properties-touch.md`](item-properties-touch.md) — the `.properties` touch.
- [`studio-noise-filter.md`](studio-noise-filter.md) — diff noise patterns that aren't functional changes.
- [`studio-clean-and-codegen.md`](studio-clean-and-codegen.md) — diagnosing when an edit produces broken code-gen.
- [`joblet-inlining.md`](joblet-inlining.md) — adding columns multiplies by the inlining factor; measure before editing heavy joblets.
