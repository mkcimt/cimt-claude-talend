r"""
Java-style `.properties` file reader and writer.

Used across cimt-claude-talend for reading project and per-developer config.
Java-compatible enough for our needs (key=value, # comments, blank lines)
but stdlib-only and tolerant of common edge cases.

Notes on the dialect we accept:
- Comments: lines starting with `#` (after optional whitespace) and `!` (Java convention).
- Key/value separator: the first `=` on the line. Spaces around it are stripped.
  (We do NOT accept `:` or space-only separators — Talend conventions stick to `=`.)
- Values may contain `=` characters; only the first one separates.
- Trailing whitespace on values is stripped (matches `Properties.load()` behaviour).
- Empty values are valid (`key=` → empty string).
- Line continuations (`\` at end of line) are NOT supported — keep values on one line.
- Unicode `\uXXXX` escapes are NOT decoded — write values raw.

The writer preserves:
- The order of existing keys.
- Comments and blank lines between keys.
- Whitespace around `=` (uses the file's existing style, defaults to `=` with no spaces).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


_COMMENT_RE = re.compile(r"^\s*[#!]")
_KV_RE = re.compile(r"^(\s*)([^=#!\s][^=]*?)\s*=\s*(.*?)\s*$")


def load(path: Path | str) -> dict[str, str]:
    """Read a .properties file into a dict. Missing file returns empty dict."""
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        if _COMMENT_RE.match(raw) or not raw.strip():
            continue
        m = _KV_RE.match(raw)
        if not m:
            # Tolerate unrecognised lines silently — better than crashing on a typo.
            continue
        key = m.group(2).strip()
        value = m.group(3)
        out[key] = value
    return out


def get(path: Path | str, key: str, default: Optional[str] = None) -> Optional[str]:
    """Return the value for `key`, or `default` if missing/empty."""
    value = load(path).get(key)
    if value is None or value == "":
        return default
    return value


def set_value(path: Path | str, key: str, value: str) -> None:
    """
    Write `key=value` to the file, preserving order and comments.

    If the key already exists, its line is rewritten in place.
    If not, the key is appended at the end with a blank line before it
    (unless the file is empty or already ends with a blank line).

    Atomicity: writes to a tempfile in the same directory, then renames.
    """
    p = Path(path)
    if not p.exists():
        # New file with just this entry.
        p.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    lines = p.read_text(encoding="utf-8").splitlines()
    updated = False
    for i, raw in enumerate(lines):
        if _COMMENT_RE.match(raw) or not raw.strip():
            continue
        m = _KV_RE.match(raw)
        if m and m.group(2).strip() == key:
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")

    # Atomic write via tempfile in same directory.
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(p)


def unset(path: Path | str, key: str) -> bool:
    """Remove a key entirely. Returns True if removed, False if not present."""
    p = Path(path)
    if not p.exists():
        return False
    lines = p.read_text(encoding="utf-8").splitlines()
    removed = False
    out_lines: list[str] = []
    for raw in lines:
        if _COMMENT_RE.match(raw) or not raw.strip():
            out_lines.append(raw)
            continue
        m = _KV_RE.match(raw)
        if m and m.group(2).strip() == key:
            removed = True
            continue
        out_lines.append(raw)
    if removed:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        tmp.replace(p)
    return removed


if __name__ == "__main__":
    # Quick self-test when run directly.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".properties", delete=False) as f:
        f.write("# Comment 1\n")
        f.write("\n")
        f.write("key.one=value1\n")
        f.write("key.two = value two with spaces \n")
        f.write("# Comment in the middle\n")
        f.write("key.three=https://example.com/path?a=b&c=d\n")
        f.write("key.empty=\n")
        path = Path(f.name)

    loaded = load(path)
    assert loaded == {
        "key.one": "value1",
        "key.two": "value two with spaces",
        "key.three": "https://example.com/path?a=b&c=d",
        "key.empty": "",
    }, f"unexpected: {loaded}"

    assert get(path, "key.one") == "value1"
    assert get(path, "key.empty") is None  # empty → default
    assert get(path, "key.empty", "fallback") == "fallback"
    assert get(path, "key.missing") is None
    assert get(path, "key.missing", "default-val") == "default-val"

    set_value(path, "key.one", "new-value-1")
    set_value(path, "key.new", "appended")
    reloaded = load(path)
    assert reloaded["key.one"] == "new-value-1"
    assert reloaded["key.new"] == "appended"
    # Comments should be preserved.
    text = path.read_text()
    assert "# Comment 1" in text
    assert "# Comment in the middle" in text

    assert unset(path, "key.two") is True
    assert unset(path, "key.two") is False  # already gone
    reloaded = load(path)
    assert "key.two" not in reloaded

    path.unlink()
    print("properties.py self-test passed")
