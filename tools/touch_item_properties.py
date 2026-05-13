#!/usr/bin/env python3
"""
Bump modified_date and modified_product_version in a Talend .properties file.

When you edit a .item file via code (no Talend Studio), call this on each
edited .item path. It rewrites the sibling .properties file's modified_date
(to now) and modified_product_version (read from <project>/talend.project).

The Talend project root is auto-discovered: walk up from the given .item
path looking for a sibling `talend.project` file. Falls back to the env
var TALEND_PROJECT_ROOT if walking fails.

See `docs/conventions/item-properties-touch.md` in the plugin for context.

Usage:
    python touch_item_properties.py <path/to/foo_0.1.item> [...]
    python touch_item_properties.py --check <path>   # dry-run, exit 1 if no change
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

ATTR_RE = re.compile(
    r'(<additionalProperties\b[^/]*?\bkey="(?P<key>[^"]+)"[^/]*?\bvalue=")(?P<value>[^"]*)("/>)'
)


def find_talend_project(item_path: Path) -> Path:
    """Walk up from item_path until we find a directory containing talend.project."""
    cur = item_path.resolve().parent
    while cur != cur.parent:
        candidate = cur / "talend.project"
        if candidate.is_file():
            return candidate
        cur = cur.parent
    env = os.environ.get("TALEND_PROJECT_ROOT")
    if env:
        candidate = Path(env) / "talend.project"
        if candidate.is_file():
            return candidate
    sys.exit(
        f"Could not find talend.project walking up from {item_path}. "
        "Set TALEND_PROJECT_ROOT env var or invoke from within the project."
    )


def studio_patch_version(talend_project: Path) -> str:
    """Read 8.0.1.YYYYMMDD_HHMM-patch from talend.project's productVersion."""
    text = talend_project.read_text(encoding="utf-8")
    m = re.search(r'productVersion="[^"]*?(\d+\.\d+\.\d+\.\d+_\d+-patch)"', text)
    if not m:
        sys.exit(f"Could not parse productVersion from {talend_project}")
    return m.group(1)


def now_iso_local_with_ms() -> str:
    """Talend writes e.g. 2024-08-07T16:10:08.052+0200 — local time, ms, no colon in tz."""
    now = dt.datetime.now().astimezone()
    base = now.strftime("%Y-%m-%dT%H:%M:%S")
    ms = f"{now.microsecond // 1000:03d}"
    tz = now.strftime("%z")
    return f"{base}.{ms}{tz}"


def touch_one(item_path: Path, product_version: str, dry_run: bool) -> bool:
    if item_path.suffix != ".item":
        sys.exit(f"Not an .item file: {item_path}")
    props = item_path.with_suffix(".properties")
    if not props.exists():
        sys.exit(f"No matching .properties next to {item_path}")
    text = props.read_text(encoding="utf-8")
    new_date = now_iso_local_with_ms()
    found = {"modified_date": False, "modified_product_version": False}

    def replace(match: re.Match) -> str:
        key = match.group("key")
        if key == "modified_date":
            found[key] = True
            return f'{match.group(1)}{new_date}{match.group(4)}'
        if key == "modified_product_version":
            found[key] = True
            return f'{match.group(1)}{product_version}{match.group(4)}'
        return match.group(0)

    new_text = ATTR_RE.sub(replace, text)
    if not all(found.values()):
        missing = [k for k, v in found.items() if not v]
        sys.exit(
            f"{props}: missing fields {missing}; not modifying. "
            "Studio writes these on every save — investigate why this file lacks them."
        )
    if new_text == text:
        return False
    if dry_run:
        return True
    props.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("items", nargs="+", help=".item paths")
    ap.add_argument("--check", action="store_true",
                    help="Dry-run; exit 1 if any file would be changed.")
    args = ap.parse_args()

    items = [Path(raw).resolve() for raw in args.items]
    if not items:
        return 0

    # all .item files in this run share the same project root in 99% of cases;
    # cache the discovery per project root for speed.
    pv_cache: dict[Path, str] = {}
    changed = 0
    for p in items:
        tp = find_talend_project(p)
        if tp not in pv_cache:
            pv_cache[tp] = studio_patch_version(tp)
        if touch_one(p, pv_cache[tp], args.check):
            print(f"{'would update' if args.check else 'updated'}: "
                  f"{p.with_suffix('.properties')}")
            changed += 1

    if args.check and changed:
        return 1
    print(f"{'would change' if args.check else 'changed'}: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
