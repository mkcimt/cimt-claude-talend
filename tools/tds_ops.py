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
    tds_ops.py task      list <campaign> [--state S] [--invalid] [--json]
    tds_ops.py task      create <campaign> --file recs.json [--assignee E] [--apply]
    tds_ops.py dqrule    info        # DQ rules: UI-only authoring (language = DSEL)

Write verbs (datamodel/campaign/semantic/task create|update|delete) default to
--dry-run and require --apply to execute. Tasks created via `task create` are
assigned to `tds.user_email` by default (use --assignee / --unassigned).

Capability matrix and gaps: see `knowledge/tds/known-gaps.md`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
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


def load_body(args) -> dict:
    """Read a JSON request body from --file PATH or stdin (--file -)."""
    src = getattr(args, "file", None)
    if not src:
        sys.exit("This write verb needs --file PATH (JSON body) or --demo.")
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError as e:
        sys.exit(f"--file is not valid JSON: {e}")


# Demo payload builders — the documented example shapes, namespaced so live
# runs are self-contained and identifiable. See knowledge/tds/api-reference.md.
DEMO_PRODUCT_FIELDS = [
    {"name": "Id", "displayName": "Id", "type": "integer", "required": True},
    {"name": "Name", "displayName": "Name", "type": "text", "required": True},
    {"name": "Material", "displayName": "Material", "type": "text", "required": True},
    {"name": "Price", "displayName": "Price", "type": "decimal", "required": True,
     "constraints": [{"name": "scaleDecimal", "value": 2}]},
    {"name": "Quantity", "displayName": "Quantity", "type": "integer", "required": True},
    {"name": "ProductURL", "displayName": "Product URL", "type": "URL", "required": False},
]


def build_demo_datamodel(name: str) -> dict:
    return {
        "name": name,
        "displayName": f"Product (demo {name})",
        "description": "cimt demo data model created via the TDS API tool.",
        "fields": DEMO_PRODUCT_FIELDS,
    }


def build_demo_campaign(name: str, datamodel_name: str, owner: str, *,
                        version: int = 1, display_name: str | None = None) -> dict:
    """RESOLUTION-workflow demo campaign (the documented example shape).

    Only RESOLUTION is templated here; other task types need a tailored
    workflow/body via --file (see knowledge/tds/known-gaps.md).
    """
    return {
        "campaign": {
            "name": name,
            "label": f"cimt demo — {name}",
            "description": "cimt demo campaign created via the TDS API tool.",
            "owners": [owner],
            "taskType": "RESOLUTION",
            "schemaRef": {
                "namespace": "org.talend.schema",
                "name": datamodel_name,
                "version": version,
                "displayName": display_name or datamodel_name,
            },
            "taskResolutionDelay": {"value": 10, "unit": "DAYS"},
            "workflow": {
                "name": "default workflow",
                "states": [
                    {"name": "New", "label": "New", "allowedRoles": [], "translations": {},
                     "transitions": [{"name": "To validate", "label": "To validate",
                                      "targetStateName": "To validate",
                                      "allowedRoles": ["Supervisor"]}]},
                    {"name": "To validate", "label": "To validate", "allowedRoles": [],
                     "translations": {},
                     "transitions": [
                         {"name": "Accept", "label": "Accept", "targetStateName": "Resolved",
                          "allowedRoles": ["Validator"]},
                         {"name": "Reject", "label": "Reject", "targetStateName": "New",
                          "allowedRoles": ["Validator"]}]},
                    {"name": "Resolved", "label": "Resolved", "allowedRoles": ["Validator"],
                     "translations": {}, "transitions": []},
                ],
            },
        },
        "participants": {"Supervisor": [owner], "Validator": [owner]},
    }


def build_demo_semantic_regex(name: str) -> dict:
    """A self-contained REGEX semantic type (the documented edit-sandbox shape)."""
    return {
        "name": name,
        "label": name,
        "type": "REGEX",
        "validationMode": "EXACT_IGNORE_CASE_AND_ACCENT",
        "regEx": {
            "mainCategory": "AlphaNumeric",
            "validator": {"patternString": "^CIMT-[0-9]{4}$"},
        },
    }


RUN_LOG = Path(__file__).resolve().parents[1] / ".claude" / "tmp" / "tds-run.json"


def log_created(kind: str, name: str, *, deletable: bool = True) -> None:
    """Append a created object to the gitignored run log (for teardown / PR list)."""
    entries = []
    if RUN_LOG.is_file():
        try:
            entries = json.loads(RUN_LOG.read_text())
        except ValueError:
            entries = []
    entries.append({"kind": kind, "name": name, "deletable": deletable,
                    "ts": int(time.time())})
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    RUN_LOG.write_text(json.dumps(entries, indent=2))


def demo_name(sep: str = "_") -> str:
    """A unique, identifiable demo name. `sep='-'` for campaigns (name pattern
    forbids underscores), `sep='_'` for data models."""
    return f"cimt{sep}demo{sep}{int(time.time())}"


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


def cmd_datamodel_create(client: tc.TdsClient, args) -> int:
    if args.demo:
        body = build_demo_datamodel(args.name or demo_name("_"))
    else:
        body = load_body(args)
    res = client.post(SCHEMA, body)
    if client.dry_run:
        return 0
    name = (res or {}).get("name", body.get("name"))
    print(f"Created data model: {name} (v{(res or {}).get('version', 1)})")
    log_created("datamodel", name)
    return 0


def cmd_datamodel_update(client: tc.TdsClient, args) -> int:
    body = load_body(args)
    res = client.put(f"{SCHEMA}/{args.name}", body)
    if client.dry_run:
        return 0
    print(f"Updated data model: {args.name} (v{(res or {}).get('version', '?')})")
    return 0


def cmd_datamodel_delete(client: tc.TdsClient, args) -> int:
    client.delete(f"{SCHEMA}/{args.name}")
    if client.dry_run:
        return 0
    print(f"Deleted data model: {args.name}")
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


def _resolve_owner(client: tc.TdsClient, args) -> str:
    owner = getattr(args, "owner", None) or client.cfg.get("tds.user_email")
    if not owner:
        sys.exit("No campaign owner. Pass --owner EMAIL or set tds.user_email in config.")
    return owner


def cmd_campaign_create(client: tc.TdsClient, args) -> int:
    if args.demo:
        if not args.datamodel:
            sys.exit("--demo campaign needs --datamodel NAME (an existing data model).")
        owner = _resolve_owner(client, args)
        model = client.get(f"{SCHEMA}/{args.datamodel}")  # for version + displayName
        name = args.name or demo_name("-")
        body = build_demo_campaign(name, args.datamodel, owner,
                                   version=(model or {}).get("version", 1),
                                   display_name=(model or {}).get("displayName"))
    else:
        body = load_body(args)
        name = (body.get("campaign") or {}).get("name", "?")
    res = client.post(f"{DS}/campaigns/owned", body)
    if client.dry_run:
        return 0
    cid = (res or {}).get("id")
    rname = (res or {}).get("name", name)
    print(f"Created campaign: {rname}  (id {cid}, type {(res or {}).get('taskType')})")
    log_created("campaign", rname)
    return 0


def cmd_campaign_update(client: tc.TdsClient, args) -> int:
    body = load_body(args)
    client.put(f"{DS}/campaigns/owned", body)
    if client.dry_run:
        return 0
    print("Updated campaign (label/participants).")
    return 0


def cmd_campaign_delete(client: tc.TdsClient, args) -> int:
    # Live-verified: deletion is by NAME under /campaigns/owned/{name}
    # (the /campaigns/{name} and /campaigns/{id} paths return 405).
    client.delete(f"{DS}/campaigns/owned/{args.name}")
    if client.dry_run:
        return 0
    print(f"Deleted campaign: {args.name}")
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


def _poll_draft_status(client: tc.TdsClient, cid: str, tries: int = 12) -> str:
    """Poll the async draft-save status until terminal (FINISH) or attempts run out."""
    for _ in range(tries):
        st = client.get(f"{SEM}/v2/categories/{cid}/draft/status")
        val = st.get("status") if isinstance(st, dict) else st
        if str(val).upper() in ("FINISH", "FINISHED", "DONE", "PUBLISH", "OK"):
            return str(val)
        time.sleep(1)
    return str(val) if "val" in dir() else "UNKNOWN"


def cmd_semantic_create(client: tc.TdsClient, args) -> int:
    """Orchestrate the sandbox -> edit -> draft -> publish lifecycle."""
    if args.demo:
        name = args.name or ("CIMT_DEMO_" + str(int(time.time())))
        edit_body = build_demo_semantic_regex(name)
    else:
        edit_body = load_body(args)
        name = edit_body.get("name", "?")
    if client.dry_run:
        print(f"[dry-run] semantic create lifecycle for {name!r}:")
        print(f"  1) POST   {SEM}/categories/sandbox            -> {{id}}")
        print(f"  2) PATCH  {SEM}/categories/{{id}}  body:")
        print(json.dumps(edit_body, indent=2, ensure_ascii=False))
        print(f"  3) PATCH  {SEM}/v2/categories/{{id}}/draft     (async)")
        print(f"  4) GET    {SEM}/v2/categories/{{id}}/draft/status  (poll)")
        print(f"  5) POST   {SEM}/categories/{{id}}/publish")
        return 0
    sandbox = client.post(f"{SEM}/categories/sandbox") or {}
    cid = sandbox.get("id")
    if not cid:
        sys.exit(f"sandbox create returned no id: {sandbox!r}")
    print(f"  sandbox created : {cid}")
    client.patch(f"{SEM}/categories/{cid}", edit_body)
    print(f"  edited          : {edit_body.get('type')} '{name}'")
    client.patch(f"{SEM}/v2/categories/{cid}/draft")
    print(f"  draft status    : {_poll_draft_status(client, cid)}")
    client.post(f"{SEM}/categories/{cid}/publish")
    print(f"Published semantic type: {name} (id {cid})")
    log_created("semantic", cid)
    return 0


def cmd_semantic_publish(client: tc.TdsClient, args) -> int:
    client.post(f"{SEM}/categories/{args.id}/publish")
    if client.dry_run:
        return 0
    print(f"Published semantic type: {args.id}")
    return 0


def cmd_semantic_delete(client: tc.TdsClient, args) -> int:
    client.delete(f"{SEM}/categories/{args.id}")
    if client.dry_run:
        return 0
    print(f"Deleted semantic type: {args.id}")
    return 0


# --------------------------------------------------------------------------
# Tasks — campaign-scoped REST: /data-stewardship/api/v1/campaigns/owned/{name}/tasks
# (the standalone /api/v1/tasks path is 404 — tasks are always campaign-scoped)
# --------------------------------------------------------------------------
TASK_BATCH = 250


def _tasks_path(campaign: str) -> str:
    return f"{DS}/campaigns/owned/{campaign}/tasks"


def _task_assignee(client: tc.TdsClient, args) -> str | None:
    if getattr(args, "unassigned", False):
        return None
    return getattr(args, "assignee", None) or client.cfg.get("tds.user_email")


def cmd_task_list(client: tc.TdsClient, args) -> int:
    items = tc.as_list(client.get(_tasks_path(args.campaign)))
    if args.state:
        items = [t for t in items if str(t.get("currentState", "")).lower() == args.state.lower()]
    if args.invalid:
        items = [t for t in items if t.get("valid") is False]
    if args.json:
        return emit_json(items)
    rows = []
    for t in items:
        rec = t.get("record") or {}
        first = next(iter(rec.values()), "")
        rows.append([str(first)[:20], t.get("currentState", ""), str(t.get("valid")),
                     t.get("assignee") or "—"])
    print_table(rows, ["RECORD[0]", "STATE", "VALID", "ASSIGNEE"])
    print(f"\n{len(rows)} task(s) shown. NOTE: the endpoint paginates (default page ~200) — "
          "filter server-side or page for full sets.")
    return 0


def cmd_task_get(client: tc.TdsClient, args) -> int:
    # No standalone task GET; scan the campaign's tasks for the id.
    for t in tc.as_list(client.get(_tasks_path(args.campaign))):
        if t.get("id") == args.id:
            return emit_json(t)
    sys.exit(f"Task {args.id!r} not found on the current page of campaign {args.campaign!r} "
             "(endpoint paginates ~200).")


def cmd_task_create(client: tc.TdsClient, args) -> int:
    """Create tasks from a JSON file: an array of record objects (data values),
    or an array of full task objects ({type, record, ...}), or a single object."""
    data = load_body(args)
    records = data if isinstance(data, list) else [data]
    assignee = _task_assignee(client, args)
    tasks = []
    for r in records:
        if isinstance(r, dict) and "record" in r:      # already a task object
            t = dict(r)
            t.setdefault("type", args.type)
            if assignee is not None:
                t.setdefault("assignee", assignee)
        else:                                          # a bare record
            t = {"type": args.type, "record": r}
            if assignee is not None:
                t["assignee"] = assignee
        tasks.append(t)

    path = _tasks_path(args.campaign)
    if client.dry_run:
        print(f"[dry-run] POST {path}")
        print(f"  {len(tasks)} task(s), type={args.type}, "
              f"assignee={assignee or 'unassigned'}; first task:")
        if tasks:
            print(json.dumps(tasks[0], indent=2, ensure_ascii=False)[:600])
        return 0

    created = 0
    for i in range(0, len(tasks), TASK_BATCH):
        res = client.post(path, tasks[i:i + TASK_BATCH])
        created += len(res) if isinstance(res, list) else len(tasks[i:i + TASK_BATCH])
    print(f"Created {created} task(s) in campaign {args.campaign}"
          + (f", assigned to {assignee}." if assignee else ", unassigned."))
    return 0


def cmd_task_info(client: tc.TdsClient, args) -> int:
    print(
        "Tasks ARE available via the campaign-scoped REST endpoint:\n"
        "  GET  /data-stewardship/api/v1/campaigns/owned/{name}/tasks   (list; paginates ~200)\n"
        "  POST /data-stewardship/api/v1/campaigns/owned/{name}/tasks   (create; array of\n"
        '       {"type":"RESOLUTION","assignee":<user>,"record":{...}} objects)\n\n'
        "  -> `tds_ops.py task list <campaign>` / `task create <campaign> --file records.json`\n\n"
        "NOTE: the standalone /api/v1/tasks path is 404 — tasks are always campaign-scoped.\n"
        "Bulk task delete and state transitions are not exposed here — use the UI or the\n"
        "Studio components (tDataStewardshipTask*). See knowledge/tds/known-gaps.md."
    )
    return 0


def cmd_dqrule_info(client: tc.TdsClient, args) -> int:
    print(
        "Data Quality rules have NO TDS REST endpoint (probed /rules, /dq-rules,\n"
        "/dataquality/rules → HTTP 404). They are authored in the Data Stewardship UI\n"
        "(basic / advanced editor) and associated to a data model there. They ARE readable\n"
        "as part of a data model: `tds_ops.py datamodel get <name>` shows the `rulesInstances`.\n\n"
        "Rule language (advanced mode) = the Data Shaping Expression Language (DSEL), used to\n"
        "VALIDATE (not transform), plus TDS functions isInMonth/isInYear/isOfType/isOnDayOfMonth/\n"
        "isOnDayOfWeek; regex is RE2/J (no backreferences). The qlik-talend skill now carries the\n"
        "DSEL reference. See knowledge/tds/known-gaps.md."
    )
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="raw JSON output")


def _add_apply(p: argparse.ArgumentParser) -> None:
    p.add_argument("--apply", action="store_true",
                   help="execute the write (default: dry-run prints the request)")


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
    s = dma.add_parser("create")
    s.add_argument("--name", help="model name (with --demo) or override")
    s.add_argument("--file", help="JSON body path, or - for stdin")
    s.add_argument("--demo", action="store_true", help="use the built-in demo product model")
    _add_apply(s)
    s = dma.add_parser("update")
    s.add_argument("name"); s.add_argument("--file", help="JSON body path, or - for stdin")
    _add_apply(s)
    s = dma.add_parser("delete"); s.add_argument("name"); _add_apply(s)

    # campaign
    cm = obj.add_parser("campaign", help="campaigns (data-stewardship)")
    cma = cm.add_subparsers(dest="action", required=True)
    s = cma.add_parser("list")
    s.add_argument("--all", action="store_true", help="all campaigns, not just owned")
    s.add_argument("--name"); _add_json(s)
    s = cma.add_parser("get"); s.add_argument("name"); _add_json(s)
    s = cma.add_parser("create")
    s.add_argument("--name", help="campaign name (lowercase/digits/hyphen)")
    s.add_argument("--file", help="JSON body path, or - for stdin")
    s.add_argument("--demo", action="store_true", help="RESOLUTION demo campaign template")
    s.add_argument("--datamodel", help="existing data model name (required with --demo)")
    s.add_argument("--owner", help="owner username (default: tds.user_email)")
    _add_apply(s)
    s = cma.add_parser("update"); s.add_argument("--file", help="JSON body path, or - for stdin")
    _add_apply(s)
    s = cma.add_parser("delete"); s.add_argument("name"); _add_apply(s)

    # semantic
    sm = obj.add_parser("semantic", help="semantic types (semanticservice)")
    sma = sm.add_subparsers(dest="action", required=True)
    s = sma.add_parser("list"); s.add_argument("--name"); _add_json(s)
    s = sma.add_parser("get"); s.add_argument("key", help="semantic type id or name"); _add_json(s)
    s = sma.add_parser("create", help="sandbox->edit->draft->publish lifecycle")
    s.add_argument("--name", help="semantic type name (with --demo) or override")
    s.add_argument("--file", help="edit-body JSON path, or - for stdin")
    s.add_argument("--demo", action="store_true", help="built-in REGEX demo semantic type")
    _add_apply(s)
    s = sma.add_parser("publish"); s.add_argument("id"); _add_apply(s)
    s = sma.add_parser("delete"); s.add_argument("id"); _add_apply(s)

    # task — campaign-scoped records
    tk = obj.add_parser("task", help="campaign tasks / records (data-stewardship)")
    tka = tk.add_subparsers(dest="action", required=True)
    s = tka.add_parser("list")
    s.add_argument("campaign")
    s.add_argument("--state", help="filter by currentState (e.g. New)")
    s.add_argument("--invalid", action="store_true", help="only tasks failing validation")
    _add_json(s)
    s = tka.add_parser("get"); s.add_argument("campaign"); s.add_argument("id"); _add_json(s)
    s = tka.add_parser("create")
    s.add_argument("campaign")
    s.add_argument("--file", required=True,
                   help="JSON: array of records or task objects, or - for stdin")
    s.add_argument("--assignee", help="assignee username (default: tds.user_email)")
    s.add_argument("--unassigned", action="store_true", help="create without assigning")
    s.add_argument("--type", default="RESOLUTION", help="task type (default RESOLUTION)")
    _add_apply(s)
    tka.add_parser("info")

    # dqrule — UI-only authoring (info); see DSEL in the qlik-talend skill
    dq = obj.add_parser("dqrule", help="DQ rules (UI-only authoring — see info)")
    dq.add_subparsers(dest="action", required=True).add_parser("info")

    return p


DISPATCH = {
    ("datamodel", "list"): cmd_datamodel_list,
    ("datamodel", "get"): cmd_datamodel_get,
    ("datamodel", "create"): cmd_datamodel_create,
    ("datamodel", "update"): cmd_datamodel_update,
    ("datamodel", "delete"): cmd_datamodel_delete,
    ("campaign", "list"): cmd_campaign_list,
    ("campaign", "get"): cmd_campaign_get,
    ("campaign", "create"): cmd_campaign_create,
    ("campaign", "update"): cmd_campaign_update,
    ("campaign", "delete"): cmd_campaign_delete,
    ("semantic", "list"): cmd_semantic_list,
    ("semantic", "get"): cmd_semantic_get,
    ("semantic", "create"): cmd_semantic_create,
    ("semantic", "publish"): cmd_semantic_publish,
    ("semantic", "delete"): cmd_semantic_delete,
    ("task", "list"): cmd_task_list,
    ("task", "get"): cmd_task_get,
    ("task", "create"): cmd_task_create,
    ("task", "info"): cmd_task_info,
    ("dqrule", "info"): cmd_dqrule_info,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = DISPATCH.get((args.object, args.action))
    if handler is None:
        sys.exit(f"Unknown command: {args.object} {args.action}")
    # Write verbs carry --apply; absent or false → dry-run. Reads have no --apply.
    dry_run = hasattr(args, "apply") and not args.apply
    client = tc.TdsClient(dry_run=dry_run)
    try:
        rc = handler(client, args)
    except tc.TdsError as e:
        sys.exit(str(e))
    if dry_run:
        print("\n(dry-run — nothing was sent. Re-run with --apply to execute.)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
