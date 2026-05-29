#!/usr/bin/env python3
"""
tds_ops.py — manage Talend Data Stewardship (TDS) objects from the CLI.

Analogous to the kit's TMC tooling: read + write data models, campaigns and
semantic types against the TDS REST API. Stdlib only; auth/config via
tds_client.py (see `.claude/talend.local.properties`).

Usage:
    tds_ops.py datamodel list [--name SUBSTR] [--json]
    tds_ops.py datamodel get <name> [--json]
    tds_ops.py campaign  list [--all] [--name SUBSTR] [--json]
    tds_ops.py campaign  get <name> [--json]
    tds_ops.py semantic  list [--name SUBSTR] [--json]
    tds_ops.py semantic  get <name-or-id> [--json]
    tds_ops.py task      info        # tasks have no REST API — explains the path
    tds_ops.py dqrule    info        # DQ rules have no REST API — explains the path

Write verbs (datamodel/campaign/semantic create|update|delete) are added in
later phases; they default to --dry-run and require --apply to execute.

Capability matrix and gaps: see `knowledge/tds/known-gaps.md`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tds_client as tc  # noqa: E402

# API path prefixes (live-verified — see knowledge/tds/known-gaps.md)
DS = "/data-stewardship/api/v1"
SCHEMA = "/schemaservice/api/v1/schemas/org.talend.schema"
SEM = "/semanticservice"


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------
def emit_json(obj: Any) -> int:
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return 0


def print_table(rows: list[list[str]], headers: list[str]) -> None:
    if not rows:
        print("(none)")
        return
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def filter_by_name(items: list[dict], name: str | None, *, key: str = "name",
                    extra_keys: tuple[str, ...] = ("label", "displayName")) -> list[dict]:
    """Substring filter (case-insensitive) over name + a couple of label fields.

    Mirrors the TMC tooling's --name pattern; exits if nothing matches.
    """
    if not name:
        return items
    needle = name.lower()
    keys = (key,) + extra_keys
    matched = [it for it in items
               if any(needle in str(it.get(k, "")).lower() for k in keys)]
    if not matched:
        sys.exit(f"No items matching --name {name!r}.")
    return matched


# --------------------------------------------------------------------------
# Data models (schemaservice)
# --------------------------------------------------------------------------
def cmd_datamodel_list(client: tc.TdsClient, args) -> int:
    items = tc.as_list(client.get(SCHEMA))
    items = filter_by_name(items, args.name)
    if args.json:
        return emit_json(items)
    rows = [[m.get("name", ""), m.get("version", ""), m.get("displayName", "")]
            for m in sorted(items, key=lambda m: str(m.get("name", "")))]
    print_table(rows, ["NAME", "VER", "DISPLAY NAME"])
    print(f"\n{len(rows)} data model(s).")
    return 0


def cmd_datamodel_get(client: tc.TdsClient, args) -> int:
    model = client.get(f"{SCHEMA}/{args.name}")
    if args.json:
        return emit_json(model)
    print(f"Data model: {model.get('name')}  (v{model.get('version')})")
    print(f"  displayName : {model.get('displayName')}")
    print(f"  description : {model.get('description')}")
    fields = model.get("fields") or []
    print(f"  fields      : {len(fields)}")
    rows = [[f.get("name", ""), f.get("type", ""),
             "required" if f.get("required") else "", f.get("displayName", "")]
            for f in fields]
    if rows:
        print()
        print_table(rows, ["FIELD", "TYPE", "REQ", "DISPLAY NAME"])
    rules = model.get("rulesInstances") or []
    if rules:
        print(f"\n  attached DQ rule instances: {len(rules)} "
              "(read-only here; DQ rules are authored in the UI — see `dqrule info`)")
    return 0


# --------------------------------------------------------------------------
# Campaigns (data-stewardship)
# --------------------------------------------------------------------------
def cmd_campaign_list(client: tc.TdsClient, args) -> int:
    path = f"{DS}/campaigns" if args.all else f"{DS}/campaigns/owned"
    items = tc.as_list(client.get(path))
    items = filter_by_name(items, args.name)
    if args.json:
        return emit_json(items)
    rows = [[c.get("name", ""), c.get("taskType", ""), c.get("status", ""),
             c.get("label", "")]
            for c in sorted(items, key=lambda c: str(c.get("label", "")))]
    print_table(rows, ["NAME", "TYPE", "STATUS", "LABEL"])
    print(f"\n{len(rows)} campaign(s){' (all)' if args.all else ' (owned)'}.")
    return 0


def cmd_campaign_get(client: tc.TdsClient, args) -> int:
    camp = client.get(f"{DS}/campaigns/{args.name}")
    if args.json:
        return emit_json(camp)
    print(f"Campaign: {camp.get('name')}")
    print(f"  label    : {camp.get('label')}")
    print(f"  type     : {camp.get('taskType')}    status: {camp.get('status')}")
    print(f"  owners   : {', '.join(camp.get('owners') or [])}")
    ref = camp.get("schemaRef") or {}
    if ref:
        print(f"  dataModel: {ref.get('name')} (v{ref.get('version')}) — {ref.get('displayName')}")
    elif camp.get("recordStructure"):
        print("  dataModel: (schemaRef not returned on read; record structure embedded)")
    # workflow states live under workflow.states (create response) or top-level states (read)
    wf = camp.get("workflow") or {}
    states = wf.get("states") or camp.get("states") or []
    if states:
        label = wf.get("name") or "workflow"
        print(f"  {label} states: " + " -> ".join(s.get("name", "") for s in states))
    return 0


# --------------------------------------------------------------------------
# Semantic types (semanticservice)
# --------------------------------------------------------------------------
def _semantic_all(client: tc.TdsClient) -> list[dict]:
    return tc.as_list(client.get(f"{SEM}/categories"))


def cmd_semantic_list(client: tc.TdsClient, args) -> int:
    items = filter_by_name(_semantic_all(client), args.name)
    if args.json:
        return emit_json(items)
    rows = [[s.get("name", ""), s.get("type", ""), s.get("state", ""),
             s.get("label", "")]
            for s in sorted(items, key=lambda s: str(s.get("name", "")))]
    print_table(rows, ["NAME", "TYPE", "STATE", "LABEL"])
    print(f"\n{len(rows)} semantic type(s).")
    return 0


def cmd_semantic_get(client: tc.TdsClient, args) -> int:
    key = args.key
    match = None
    for s in _semantic_all(client):
        if s.get("id") == key or s.get("name") == key:
            match = s
            break
    if match is None:
        sys.exit(f"No semantic type with id or name {key!r}.")
    if args.json:
        return emit_json(match)
    print(f"Semantic type: {match.get('name')}  (id {match.get('id')})")
    for k in ("label", "type", "state", "validationMode", "description"):
        if match.get(k) not in (None, ""):
            print(f"  {k:15}: {match.get(k)}")
    return 0


# --------------------------------------------------------------------------
# Tasks & DQ rules — no REST API (honest info verbs, not no-ops)
# --------------------------------------------------------------------------
def cmd_task_info(client: tc.TdsClient, args) -> int:
    print(
        "Tasks have NO Talend Data Stewardship REST endpoint.\n"
        "  Verified: /data-stewardship/api/v1/tasks* → HTTP 404, and the user guide\n"
        "  documents no task API page.\n\n"
        "Tasks are the records inside a campaign and are managed via:\n"
        "  - Studio components: tDataStewardshipTaskInput (load/create), \n"
        "    tDataStewardshipTaskOutput, tDataStewardshipTaskDelete — filtered with TQL;\n"
        "  - the Data Stewardship UI (manual resolution / transitions / assignment).\n\n"
        "For demos, create the campaign with this tool, then seed tasks from a Studio\n"
        "job (tDataStewardshipTaskInput). See knowledge/tds/known-gaps.md."
    )
    return 0


def cmd_dqrule_info(client: tc.TdsClient, args) -> int:
    print(
        "Data Quality rules have NO TDS REST endpoint (probed /rules, /dq-rules,\n"
        "/dataquality/rules → HTTP 404). They are authored in the Data Stewardship UI\n"
        "(basic / advanced editor) and associated to a data model there.\n\n"
        "They ARE readable as part of a data model: `tds_ops.py datamodel get <name>`\n"
        "shows attached rule instances (the `rulesInstances` field). Authoring stays UI-only.\n"
        "See knowledge/tds/known-gaps.md."
    )
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="raw JSON output")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tds_ops.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    obj = p.add_subparsers(dest="object", required=True)

    # datamodel
    dm = obj.add_parser("datamodel", help="data models (schemaservice)")
    dma = dm.add_subparsers(dest="action", required=True)
    s = dma.add_parser("list"); s.add_argument("--name"); _add_json(s)
    s = dma.add_parser("get"); s.add_argument("name"); _add_json(s)

    # campaign
    cm = obj.add_parser("campaign", help="campaigns (data-stewardship)")
    cma = cm.add_subparsers(dest="action", required=True)
    s = cma.add_parser("list")
    s.add_argument("--all", action="store_true", help="all campaigns, not just owned")
    s.add_argument("--name"); _add_json(s)
    s = cma.add_parser("get"); s.add_argument("name"); _add_json(s)

    # semantic
    sm = obj.add_parser("semantic", help="semantic types (semanticservice)")
    sma = sm.add_subparsers(dest="action", required=True)
    s = sma.add_parser("list"); s.add_argument("--name"); _add_json(s)
    s = sma.add_parser("get"); s.add_argument("key", help="semantic type id or name"); _add_json(s)

    # task / dqrule — info only (no REST API)
    tk = obj.add_parser("task", help="tasks (no REST API — see info)")
    tk.add_subparsers(dest="action", required=True).add_parser("info")
    dq = obj.add_parser("dqrule", help="DQ rules (no REST API — see info)")
    dq.add_subparsers(dest="action", required=True).add_parser("info")

    return p


DISPATCH = {
    ("datamodel", "list"): cmd_datamodel_list,
    ("datamodel", "get"): cmd_datamodel_get,
    ("campaign", "list"): cmd_campaign_list,
    ("campaign", "get"): cmd_campaign_get,
    ("semantic", "list"): cmd_semantic_list,
    ("semantic", "get"): cmd_semantic_get,
    ("task", "info"): cmd_task_info,
    ("dqrule", "info"): cmd_dqrule_info,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = DISPATCH.get((args.object, args.action))
    if handler is None:
        sys.exit(f"Unknown command: {args.object} {args.action}")
    client = tc.TdsClient()
    try:
        return handler(client, args)
    except tc.TdsError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    sys.exit(main())
