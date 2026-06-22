#!/usr/bin/env python3
"""
intake_to_excel.py — render the canonical intake JSON (from project_intake.py)
into a presentation `.xlsx` workbook (phase 2 of /project-intake).

PURE rendering: no analysis logic lives here. Every value comes straight from the
canonical document, so the workbook and the JSON can never disagree. Each sheet
carries a *Provenance* column (static / tmc / manual) and is colour-coded, so a
reader sees at a glance what was derived from code vs. what still needs TMC or a
human.

openpyxl is an OPTIONAL dependency (only this renderer needs it; the phase-1
analyzer stays stdlib-only so the canonical JSON is always producible). Install
with `pip install openpyxl` — see INSTALL.md.

Usage:
    intake_to_excel.py --in intake.json --out intake.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import talend_complexity as tcx  # noqa: E402  (stdlib-only; used for the signal-key list)

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    _HAVE_OPENPYXL = True
except ImportError:  # pragma: no cover - exercised only when dependency absent
    _HAVE_OPENPYXL = False

_HEADER_FILL = "1F3864"      # dark blue
_PROV_FILL = {"static": "E2EFDA", "tmc": "DDEBF7", "manual": "FCE4D6"}  # green / blue / amber


def _require_openpyxl() -> None:
    if not _HAVE_OPENPYXL:
        raise RuntimeError(
            "openpyxl is required for the Excel renderer. Install it with "
            "`pip install openpyxl` (the phase-1 analyzer needs no dependencies)."
        )


def _names(doc: dict) -> dict[str, str]:
    return {a["artifact_id"]: a["name"] for a in doc["artifacts"]}


def _sysmap(doc: dict) -> dict[str, dict]:
    return {s["system_id"]: s for s in doc["systems"]}


def _header(ws, headers: list[str]) -> None:
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=_HEADER_FILL)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _autosize(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _prov_fill(row_cells, provenance: str) -> None:
    color = _PROV_FILL.get(provenance)
    if color:
        for cell in row_cells:
            cell.fill = PatternFill("solid", fgColor=color)


# --------------------------------------------------------------------------- #
# Sheets
# --------------------------------------------------------------------------- #
def sheet_summary(wb, doc: dict) -> None:
    ws = wb.active
    ws.title = "Summary"
    p = doc["project"]
    ws["A1"] = "Talend Project Intake — Summary"
    ws["A1"].font = Font(bold=True, size=14)
    rows = [
        ("Project", p["name"]),
        ("Talend version", p["product_version"]),
        ("Scanned path", p["scanned_path"]),
        ("Generated at", doc["generated_at"]),
        ("Config version", doc["generator"].get("config_version", "")),
        ("", ""),
        ("Distinct external systems", len(doc["systems"])),
        ("Proposed interfaces", len(doc["interfaces"])),
        ("Gaps to resolve", len(doc["gaps"])),
        ("Parse errors", len(p.get("parse_errors", []))),
    ]
    r = 3
    for label, value in rows:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        ws.cell(row=r, column=2, value=value)
        r += 1

    ws.cell(row=r + 1, column=1, value="Artifact counts").font = Font(bold=True, size=12)
    r += 2
    for k, v in p["artifact_counts"].items():
        if v:
            ws.cell(row=r, column=1, value=k)
            ws.cell(row=r, column=2, value=v)
            r += 1

    ws.cell(row=r + 1, column=1, value="Complexity (estimated, uncalibrated)").font = Font(bold=True, size=12)
    r += 2
    from collections import Counter
    hist = Counter(a["complexity"]["bucket"] for a in doc["artifacts"]
                   if a.get("complexity"))
    for b in ("Very Simple", "Simple", "Moderate", "Complex", "Very Complex"):
        if hist.get(b):
            ws.cell(row=r, column=1, value=b)
            ws.cell(row=r, column=2, value=hist[b])
            r += 1

    ws.cell(row=r + 1, column=1, value="Provenance legend").font = Font(bold=True, size=12)
    r += 2
    for prov, desc in (("static", "derived from the Talend project on disk"),
                       ("tmc", "from Talend Management Console (phase 3)"),
                       ("manual", "needs human/customer input (phase 4)")):
        c1 = ws.cell(row=r, column=1, value=prov)
        c1.fill = PatternFill("solid", fgColor=_PROV_FILL[prov])
        ws.cell(row=r, column=2, value=desc)
        r += 1
    _autosize(ws, [26, 60])


def sheet_infrastructure(wb, doc: dict) -> None:
    ws = wb.create_sheet("Infrastructure")
    infra = doc["infrastructure"]
    _header(ws, ["Category", "Name", "Detail", "Status", "Provenance"])
    r = 2
    if not doc["environments"] and not infra["engines"]:
        ws.cell(row=r, column=1, value="(empty — populate via TMC enrichment, phase 3)")
        r += 1
    for env in doc["environments"]:
        cells = [ws.cell(row=r, column=1, value="Environment"),
                 ws.cell(row=r, column=2, value=env.get("name")),
                 ws.cell(row=r, column=3, value=env.get("description")),
                 ws.cell(row=r, column=4, value=""),
                 ws.cell(row=r, column=5, value=env.get("provenance", "tmc"))]
        _prov_fill(cells, env.get("provenance", "tmc"))
        r += 1
    for eng in infra["engines"]:
        cells = [ws.cell(row=r, column=1, value="Engine"),
                 ws.cell(row=r, column=2, value=eng.get("name")),
                 ws.cell(row=r, column=3, value=",".join(eng.get("run_profiles", []))),
                 ws.cell(row=r, column=4, value=eng.get("status")),
                 ws.cell(row=r, column=5, value=eng.get("provenance", "tmc"))]
        _prov_fill(cells, eng.get("provenance", "tmc"))
        r += 1
    for note in infra.get("manual_notes", []):
        ws.cell(row=r, column=1, value="Manual note")
        ws.cell(row=r, column=3, value=note.get("text"))
        ws.cell(row=r, column=5, value="manual")
        r += 1
    _autosize(ws, [16, 28, 40, 16, 12])


def sheet_artifacts(wb, doc: dict) -> None:
    ws = wb.create_sheet("Artifacts")
    _header(ws, ["Name", "Type", "Version", "Folder", "Complexity", "Score",
                 "#Read", "#Write", "Calls", "Flags", "Provenance"])
    r = 2
    for a in sorted(doc["artifacts"], key=lambda x: (x["type"], x["name"])):
        cx = a.get("complexity") or {}
        cells = [
            ws.cell(row=r, column=1, value=a["name"]),
            ws.cell(row=r, column=2, value=a["type"]),
            ws.cell(row=r, column=3, value=a["item_version"]),
            ws.cell(row=r, column=4, value=str(Path(a["path"]).parent)),
            ws.cell(row=r, column=5, value=cx.get("bucket")),
            ws.cell(row=r, column=6, value=cx.get("score")),
            ws.cell(row=r, column=7, value=len(a["systems_read"])),
            ws.cell(row=r, column=8, value=len(a["systems_write"])),
            ws.cell(row=r, column=9, value=", ".join(c["target_name"] for c in a["calls"])),
            ws.cell(row=r, column=10, value="; ".join(a.get("non_standard_flags", []))),
            ws.cell(row=r, column=11, value=a["provenance"]),
        ]
        _prov_fill(cells, a["provenance"])
        r += 1
    ws.auto_filter.ref = f"A1:K{max(2, r - 1)}"
    _autosize(ws, [34, 12, 9, 28, 14, 8, 7, 7, 30, 30, 12])


def sheet_systems(wb, doc: dict) -> None:
    ws = wb.create_sheet("Systems")
    _header(ws, ["Family", "Technology", "Host", "Database", "Schema", "URI/Endpoint",
                 "Objects", "Resolved", "Confidence", "Provenance"])
    r = 2
    for s in doc["systems"]:
        ident = s["identity"]
        cells = [
            ws.cell(row=r, column=1, value=s["family"]),
            ws.cell(row=r, column=2, value=s["technology"]),
            ws.cell(row=r, column=3, value=ident.get("host")),
            ws.cell(row=r, column=4, value=ident.get("database")),
            ws.cell(row=r, column=5, value=ident.get("schema")),
            ws.cell(row=r, column=6, value=ident.get("uri") if ident.get("uri") != "(unresolved)"
                    else ident.get("endpoint")),
            ws.cell(row=r, column=7, value=", ".join(s.get("objects", [])[:10])),
            ws.cell(row=r, column=8, value="yes" if s["resolved"] else "no"),
            ws.cell(row=r, column=9, value=s["confidence"]),
            ws.cell(row=r, column=10, value=s["provenance"]),
        ]
        _prov_fill(cells, s["provenance"])
        r += 1
    ws.auto_filter.ref = f"A1:J{max(2, r - 1)}"
    _autosize(ws, [14, 22, 22, 18, 14, 30, 30, 9, 11, 12])


def sheet_system_usage(wb, doc: dict) -> None:
    """Read/write matrix, flattened to one row per system with the artifacts that touch it."""
    ws = wb.create_sheet("System Read-Write")
    _header(ws, ["Family", "Technology", "Read by", "Written by"])
    names = _names(doc)
    r = 2
    for s in doc["systems"]:
        sid = s["system_id"]
        read_by = [names[a["artifact_id"]] for a in doc["artifacts"] if sid in a["systems_read"]]
        write_by = [names[a["artifact_id"]] for a in doc["artifacts"] if sid in a["systems_write"]]
        ws.cell(row=r, column=1, value=s["family"])
        ws.cell(row=r, column=2, value=s["technology"])
        ws.cell(row=r, column=3, value=", ".join(sorted(read_by)))
        ws.cell(row=r, column=4, value=", ".join(sorted(write_by)))
        r += 1
    _autosize(ws, [14, 22, 50, 50])


def sheet_complexity(wb, doc: dict) -> None:
    ws = wb.create_sheet("Complexity")
    signal_keys = list(tcx.DEFAULT_CONFIG["signals"].keys())
    _header(ws, ["Name", "Type", "Bucket", "Score", "Calibrated"] + signal_keys)
    r = 2
    for a in sorted(doc["artifacts"], key=lambda x: -(x.get("complexity") or {}).get("score", 0)):
        cx = a.get("complexity")
        if not cx:
            continue
        ws.cell(row=r, column=1, value=a["name"])
        ws.cell(row=r, column=2, value=a["type"])
        ws.cell(row=r, column=3, value=cx["bucket"])
        ws.cell(row=r, column=4, value=cx["score"])
        ws.cell(row=r, column=5, value="yes" if cx["calibrated"] else "no")
        for i, k in enumerate(signal_keys, start=6):
            ws.cell(row=r, column=i, value=cx["signals"].get(k))
        r += 1
    ws.auto_filter.ref = f"A1:{get_column_letter(5 + len(signal_keys))}{max(2, r - 1)}"
    _autosize(ws, [34, 12, 14, 8, 10] + [10] * len(signal_keys))


def sheet_interfaces(wb, doc: dict) -> None:
    ws = wb.create_sheet("Interfaces")
    _header(ws, ["Interface", "Label", "Status", "Confidence", "Members",
                 "Entry points", "Systems touched", "Ambiguous", "Provenance"])
    names = _names(doc)
    sysmap = _sysmap(doc)
    r = 2
    for i in doc["interfaces"]:
        cells = [
            ws.cell(row=r, column=1, value=i["interface_id"]),
            ws.cell(row=r, column=2, value=i["label"]),
            ws.cell(row=r, column=3, value=i["status"]),
            ws.cell(row=r, column=4, value=i["confidence"]),
            ws.cell(row=r, column=5, value=", ".join(names.get(m, m) for m in i["member_artifacts"])),
            ws.cell(row=r, column=6, value=", ".join(names.get(m, m) for m in i["entry_points"])),
            ws.cell(row=r, column=7, value=", ".join(sysmap[s]["technology"]
                    for s in i["systems_touched"] if s in sysmap)),
            ws.cell(row=r, column=8, value=", ".join(names.get(m, m) for m in i["ambiguous_members"])),
            ws.cell(row=r, column=9, value=i["provenance"]),
        ]
        _prov_fill(cells, i["provenance"])
        r += 1
    _autosize(ws, [16, 24, 12, 12, 44, 28, 36, 24, 12])


def sheet_orchestration(wb, doc: dict) -> None:
    ws = wb.create_sheet("Orchestration (TMC)")
    _header(ws, ["Plan", "Step", "Tasks (parallel)", "Condition", "Trigger", "Provenance"])
    r = 2
    plans = doc["tmc"]["plans"]
    if not plans:
        ws.cell(row=r, column=1, value="(empty — populate via TMC enrichment, phase 3: "
                                       "plans tell you which jobs run together)")
        _autosize(ws, [20, 16, 40, 20, 20, 12])
        return
    for plan in plans:
        for step in plan.get("steps", []):
            cells = [ws.cell(row=r, column=1, value=plan.get("name")),
                     ws.cell(row=r, column=2, value=step.get("step_name")),
                     ws.cell(row=r, column=3, value=", ".join(step.get("step_task_ids", []))),
                     ws.cell(row=r, column=4, value=step.get("step_condition")),
                     ws.cell(row=r, column=5, value=plan.get("trigger_schedule")),
                     ws.cell(row=r, column=6, value="tmc")]
            _prov_fill(cells, "tmc")
            r += 1
    _autosize(ws, [20, 16, 40, 20, 20, 12])


def sheet_gaps(wb, doc: dict) -> None:
    ws = wb.create_sheet("Gaps")
    _header(ws, ["Gap ID", "Kind", "Reference", "Description", "Suggested question",
                 "Resolution (fill in)", "Provenance"])
    r = 2
    for g in doc["gaps"]:
        ref = ", ".join(f"{k}={v}" for k, v in g["ref"].items() if v)
        cells = [
            ws.cell(row=r, column=1, value=g["gap_id"]),
            ws.cell(row=r, column=2, value=g["kind"]),
            ws.cell(row=r, column=3, value=ref),
            ws.cell(row=r, column=4, value=g["description"]),
            ws.cell(row=r, column=5, value=g["suggested_question"]),
            ws.cell(row=r, column=6, value=g.get("resolution") or ""),
            ws.cell(row=r, column=7, value=g["provenance"]),
        ]
        _prov_fill(cells, g["provenance"])
        r += 1
    ws.auto_filter.ref = f"A1:G{max(2, r - 1)}"
    _autosize(ws, [12, 22, 26, 46, 46, 30, 12])


def render(doc: dict, out_path: Path | str) -> Path:
    """Render the canonical intake document to an .xlsx workbook. Returns the path."""
    _require_openpyxl()
    wb = Workbook()
    sheet_summary(wb, doc)
    sheet_infrastructure(wb, doc)
    sheet_interfaces(wb, doc)
    sheet_artifacts(wb, doc)
    sheet_systems(wb, doc)
    sheet_system_usage(wb, doc)
    sheet_complexity(wb, doc)
    sheet_orchestration(wb, doc)
    sheet_gaps(wb, doc)
    out = Path(out_path)
    wb.save(out)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render intake JSON to an .xlsx workbook (phase 2).")
    p.add_argument("--in", dest="in_path", required=True, help="canonical intake JSON")
    p.add_argument("--out", dest="out_path", required=True, help="output .xlsx path")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    doc = json.loads(Path(args.in_path).read_text(encoding="utf-8"))
    out = render(doc, args.out_path)
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
