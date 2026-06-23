"""
talend_findings.py — deterministic static-review findings for a parsed `.item`.

The *breadth* layer of the intake's review dimension: cheap, project-wide,
high-precision heuristics that flag candidate issues — lookup / SQL performance,
dead / inactive code, and missing error handling. Precision over recall: only
patterns that are reliably detectable from the XML land here, so the list stays
trustworthy.

Hard semantic bugs (guard completeness, auth bypass, …) are NOT decided here —
they need judgement. Artifacts that warrant the *depth* pass are triaged
(`needs_review`) to the existing `talend-code-reviewer` agent /
`knowledge/code-review/principles.md`. (Two-tier, mirroring the complexity model.)

Each finding: {severity, category, detail, location, provenance:"static"}.
This deterministic Tier-1 catalog emits `perf | smell | dead_code`; the `bug`
severity is reserved for the Tier-2 depth pass (the `talend-code-reviewer`),
which is where hard semantic bugs are decided.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import talend_item as ti  # noqa: E402

_QUERY_KEYS = ("QUERY", "QUERYSTORE", "ELT_QUERY", "SQLQUERY")
_ERROR_HANDLING_COMPONENTS = {"tDie", "tWarn", "tLogCatcher", "tAssertCatcher",
                              "tFlowMeterCatcher", "tStatCatcher"}
_EXECUTABLE_TYPES = {"job", "route", "service", "spark_job", "spark_streaming_job", "mr_job"}

_SELECT_STAR_RE = re.compile(r"select\s+\*", re.IGNORECASE)
_LEADING_WILDCARD_RE = re.compile(r"like\s+'?%", re.IGNORECASE)


def _f(severity: str, category: str, detail: str, location: str = "") -> dict:
    return {"severity": severity, "category": category, "detail": detail,
            "location": location, "provenance": "static"}


def _writes_externally(artifact: dict) -> bool:
    return any(c.get("direction") in ("write", "both") for c in artifact.get("components", []))


def _has_error_handling(model: ti.ItemModel) -> bool:
    # Only ACTIVE handlers count — a disabled tDie/tWarn provides no runtime protection.
    if any(n.component in _ERROR_HANDLING_COMPONENTS for n in model.active_nodes()):
        return True
    return any(c.connector.upper() == "REJECT" for c in model.connections)


def extract(model: ti.ItemModel, artifact: dict) -> list[dict]:
    """Deterministic findings for one artifact. Never raises."""
    out: list[dict] = []

    # --- Performance: reload-at-each-row tMap lookups -----------------------
    for n in model.active_nodes():
        if n.mapper and n.mapper.n_reload_lookups:
            out.append(_f("perf", "lookup_reload",
                          f"tMap has {n.mapper.n_reload_lookups} reload-at-each-row lookup(s) "
                          "(the lookup is re-read for every input row)", n.unique_name))

    # --- SQL smells ---------------------------------------------------------
    for n in model.active_nodes():
        for k in _QUERY_KEYS:
            q = n.params.get(k)
            if not q:
                continue
            if _SELECT_STAR_RE.search(q):
                out.append(_f("smell", "sql_select_star",
                              "SELECT * in query (binds to schema drift; fetches unused columns)",
                              n.unique_name))
            if _LEADING_WILDCARD_RE.search(q):
                out.append(_f("perf", "sql_leading_wildcard",
                              "leading-wildcard LIKE '%…' (non-sargable, forces a scan)",
                              n.unique_name))
            if "+context." in q.replace(" ", "") or "globalMap" in q:
                out.append(_f("smell", "sql_dynamic",
                              "dynamically concatenated SQL (maintainability / injection surface)",
                              n.unique_name))

    # --- Dead / inactive code ----------------------------------------------
    inactive = [n for n in model.nodes if not n.active]
    if inactive:
        out.append(_f("dead_code", "inactive_components",
                      f"{len(inactive)} inactive (disabled) component(s) left in the job",
                      ", ".join(sorted({n.unique_name for n in inactive})[:8])))

    # --- Missing error handling on a job that writes externally ------------
    if artifact.get("type") in _EXECUTABLE_TYPES and _writes_externally(artifact):
        if not _has_error_handling(model):
            out.append(_f("smell", "no_error_handling",
                          "writes to an external system but has no tDie/tWarn/tLogCatcher and "
                          "no reject flow — failures may pass silently"))

    return out


def summarize(all_findings: list[dict]) -> dict:
    """Project-level rollup (each finding already tagged with an `artifact` by the caller)."""
    by_sev: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for fnd in all_findings:
        by_sev[fnd["severity"]] = by_sev.get(fnd["severity"], 0) + 1
        by_cat[fnd["category"]] = by_cat.get(fnd["category"], 0) + 1
    return {
        "total": len(all_findings),
        "by_severity": dict(sorted(by_sev.items(), key=lambda kv: -kv[1])),
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        "note": ("Deterministic breadth findings (high precision). Hard semantic bugs are "
                 "NOT covered here — artifacts flagged complexity.needs_llm_review go to the "
                 "talend-code-reviewer depth pass (see knowledge/code-review/principles.md)."),
        "provenance": "static",
    }


if __name__ == "__main__":
    import tempfile

    ITEM = """<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <node componentName="tOracleInput">
        <elementParameter name="UNIQUE_NAME" value="in1"/>
        <elementParameter name="QUERY" value="SELECT * FROM orders WHERE name LIKE '%x'"/>
      </node>
      <node componentName="tMap">
        <elementParameter name="UNIQUE_NAME" value="m1"/>
        <nodeData xsi:type="talendmapper:MapperData">
          <inputTables name="main"/>
          <inputTables name="lk" lookupMode="RELOAD"/>
          <outputTables name="o"><mapperTableEntries name="x" expression="main.x"/></outputTables>
        </nodeData>
      </node>
      <node componentName="tMSSqlOutput">
        <elementParameter name="UNIQUE_NAME" value="out1"/>
        <elementParameter name="TABLE" value="dbo.orders"/>
      </node>
      <node componentName="tOracleInput">
        <elementParameter name="UNIQUE_NAME" value="dead1"/>
        <elementParameter name="ACTIVATE" value="false"/>
      </node>
    </talendfile:ProcessType>"""

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.item"
        p.write_text(ITEM, encoding="utf-8")
        model = ti.parse_item(p)
        artifact = {"type": "job", "components": [
            {"direction": "read", "family": "DB"}, {"direction": "write", "family": "DB"}]}
        fnds = extract(model, artifact)
        cats = {f["category"] for f in fnds}
        assert "lookup_reload" in cats, cats
        assert "sql_select_star" in cats
        assert "sql_leading_wildcard" in cats
        assert "inactive_components" in cats
        assert "no_error_handling" in cats   # writes to MS SQL, no tDie/reject
        # reload lookup located on the tMap
        rl = next(f for f in fnds if f["category"] == "lookup_reload")
        assert rl["location"] == "m1", rl

        summ = summarize([dict(f, artifact="x") for f in fnds])
        assert summ["total"] == len(fnds)
        assert summ["by_severity"].get("perf", 0) >= 1
        assert summ["by_category"].get("sql_select_star") == 1

        # A job with error handling + no external write -> no no_error_handling finding.
        ITEM2 = ('<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x">'
                 '<node componentName="tFileInputDelimited"><elementParameter name="UNIQUE_NAME" value="i"/></node>'
                 '<node componentName="tLogRow"><elementParameter name="UNIQUE_NAME" value="l"/></node>'
                 '</talendfile:ProcessType>')
        p2 = Path(d) / "y.item"
        p2.write_text(ITEM2, encoding="utf-8")
        fn2 = extract(ti.parse_item(p2), {"type": "job", "components": [{"direction": "read", "family": "File"}]})
        assert not any(f["category"] == "no_error_handling" for f in fn2)

    print("talend_findings.py self-test passed")
