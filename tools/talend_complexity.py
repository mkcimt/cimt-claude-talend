"""
talend_complexity.py — deterministic complexity score for one Talend job/route,
computed purely from its parsed `.item` (no execution, no Talend Audit licence).

Buckets reproduce Talend Audit's five classes (Very Simple … Very Complex) so the
output is comparable to an Audit export when one exists. The score is a weighted,
soft-capped sum of static signals; **every** weight, cap, divisor and threshold
lives in `DEFAULT_CONFIG` so calibration against a real project + a real Audit
export needs zero code edits. Until then output is labelled `calibrated=False`.

The default thresholds are an UNCALIBRATED baseline chosen so a real-world-sized
project produces a believable spread (most artifacts Simple/Moderate, a tail of
Complex), rather than a fitted Audit alignment — that still requires calibration.

The high-weight signals (tMap=3, lookups=2, runjob_depth=3, loops=3) deliberately
mirror the Opus-tier triggers in `knowledge/documentation/conventions.md`, keeping
this metric and the doc's model-selection heuristic consistent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import component_catalog as cat  # noqa: E402
import talend_item as ti  # noqa: E402

_MAP_COMPONENTS = {"tMap", "tXMLMap", "tHMap"}
_LOOP_COMPONENTS = {"tLoop", "tForeach", "tFileList", "tFlowToIterate",
                    "tInfiniteLoop", "tLoopRDS"}
_FLOW_CONTROL_COMPONENTS = {"tDie", "tWarn", "tAssert", "tLogCatcher",
                            "tFlowMeterCatcher", "tStatCatcher", "tAssertCatcher"}
_QUERY_KEYS = ("QUERY", "QUERYSTORE", "ELT_QUERY", "SQLQUERY")
_CODE_COMPONENTS = {"tJava", "tJavaRow", "tJavaFlex"}

# All tunables in one place. Calibration overwrites this dict; no code changes.
DEFAULT_CONFIG: dict = {
    "config_version": "default-uncalibrated-v1",
    # signal -> (weight, cap, divisor)  — divisor None means raw count.
    "signals": {
        "n_components":    (1.0, 60, None),
        "n_connections":   (0.5, 80, None),
        "n_maps":          (3.0, 12, None),
        "n_map_out_expr":  (0.4, 60, None),
        "n_map_lookups":   (2.0, 10, None),
        "n_subjobs":       (1.0, 15, None),
        "n_runjob":        (2.0, 10, None),
        "runjob_depth":    (3.0, 6, None),
        "n_ext_systems":   (2.5, 8, None),
        "sql_lines":       (1.0, 20, 10),
        "n_sql_dynamic":   (1.5, 6, None),
        "code_lines":      (1.0, 20, 15),
        "n_routines_used": (0.8, 10, None),
        "n_loops":         (3.0, 6, None),
        "n_context_vars":  (0.2, 30, None),
        "n_flow_control":  (0.5, 15, None),
    },
    # Upper score bound (inclusive) for each bucket, in order. UNCALIBRATED baseline
    # tuned to a realistic spread on real-world-sized projects (small synthetic jobs
    # score < 15); recalibrate against a Talend Audit export per the module docstring.
    "buckets": [
        ("Very Simple", 15),
        ("Simple", 40),
        ("Moderate", 80),
        ("Complex", 130),
        ("Very Complex", float("inf")),
    ],
}


def _count_lines(text: str) -> int:
    return sum(1 for ln in (text or "").splitlines() if ln.strip())


def extract_signals(
    model: ti.ItemModel,
    artifact_type: str = "job",
    ext_systems: Optional[int] = None,
    runjob_depth: Optional[int] = None,
    routine_names: Optional[set[str]] = None,
) -> dict:
    """Pull the static complexity signals from a parsed `.item`.

    `ext_systems` / `runjob_depth` are cross-file facts supplied by the
    orchestrator; if omitted they are approximated single-file and the
    corresponding `*_approx` flag is set.
    """
    nodes = model.active_nodes()
    routine_names = routine_names or set()

    approx = {"runjob_depth_approx": False, "ext_systems_approx": False}

    n_runjob = len([n for n in nodes if n.component in cat.CALL_COMPONENTS])
    n_maps = len([n for n in nodes if n.component in _MAP_COMPONENTS])

    n_map_out_expr = n_map_lookups = 0
    for n in nodes:
        if n.mapper:
            n_map_out_expr += n.mapper.n_output_expressions + n.mapper.n_var_expressions
            n_map_lookups += n.mapper.n_lookups

    sql_lines = 0
    n_sql_dynamic = 0
    for n in nodes:
        for k in _QUERY_KEYS:
            q = n.params.get(k)
            if q:
                sql_lines += _count_lines(q)
                if ("+context" in q.replace(" ", "")) or ("globalMap" in q):
                    n_sql_dynamic += 1

    code_lines = sum(_count_lines(n.params.get("CODE", ""))
                     for n in nodes if n.component in _CODE_COMPONENTS)

    n_routines_used = 0
    if routine_names:
        blob = " ".join(
            (n.params.get("CODE", "") + " " + " ".join(
                v for k, v in n.params.items() if k in _QUERY_KEYS))
            for n in nodes)
        n_routines_used = len({r for r in routine_names if r and (r + ".") in blob})

    iterate_conns = len([c for c in model.connections if c.connector.upper() == "ITERATE"])
    n_loops = iterate_conns + len([n for n in nodes if n.component in _LOOP_COMPONENTS])

    flow_conns = len([c for c in model.connections
                      if c.connector.upper().startswith(("RUN_IF", "ON_"))
                      and "OK" not in c.connector.upper()])
    n_flow_control = flow_conns + len([n for n in nodes
                                       if n.component in _FLOW_CONTROL_COMPONENTS])

    if ext_systems is None:
        techs = set()
        for n in nodes:
            info = cat.classify_component(n.component, n.params)
            if not info["is_internal"] and info["technology"] != cat.UNKNOWN:
                techs.add((info["family"], info["technology"]))
        ext_systems = len(techs)
        approx["ext_systems_approx"] = True

    if runjob_depth is None:
        runjob_depth = 1 if n_runjob > 0 else 0
        approx["runjob_depth_approx"] = n_runjob > 0

    signals = {
        "n_components": len(nodes),
        "n_connections": len(model.connections),
        "n_maps": n_maps,
        "n_map_out_expr": n_map_out_expr,
        "n_map_lookups": n_map_lookups,
        "n_subjobs": model.subjob_count,
        "n_runjob": n_runjob,
        "runjob_depth": runjob_depth,
        "n_ext_systems": ext_systems,
        "sql_lines": sql_lines,
        "n_sql_dynamic": n_sql_dynamic,
        "code_lines": code_lines,
        "n_routines_used": n_routines_used,
        "n_loops": n_loops,
        "n_context_vars": len(model.context_vars),
        "n_flow_control": n_flow_control,
        "_approx": approx,
    }
    return signals


def score(signals: dict, config: dict = DEFAULT_CONFIG) -> float:
    """Weighted, soft-capped sum. Line-based signals are scaled by their divisor first."""
    total = 0.0
    for name, (weight, cap, div) in config["signals"].items():
        value = float(signals.get(name, 0) or 0)
        if div:
            value = value / div
        total += weight * min(value, cap)
    return round(total, 2)


def bucket(score_value: float, config: dict = DEFAULT_CONFIG) -> str:
    for label, upper in config["buckets"]:
        if score_value <= upper:
            return label
    return config["buckets"][-1][0]


def assess(
    model: ti.ItemModel,
    artifact_type: str = "job",
    config: dict = DEFAULT_CONFIG,
    ext_systems: Optional[int] = None,
    runjob_depth: Optional[int] = None,
    routine_names: Optional[set[str]] = None,
) -> dict:
    """Convenience: signals + score + bucket + provenance, as the schema's complexity block."""
    signals = extract_signals(model, artifact_type, ext_systems, runjob_depth, routine_names)
    approx = signals.pop("_approx")
    sc = score(signals, config)
    return {
        "signals": signals,
        "score": sc,
        "bucket": bucket(sc, config),
        "calibrated": config.get("config_version", "").startswith("calibrated"),
        "config_version": config.get("config_version", ""),
        "approx_flags": approx,
        "provenance": "static",
    }


if __name__ == "__main__":
    import tempfile

    # 3-component linear job -> Very Simple.
    SIMPLE = """<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x">
      <node componentName="tFileInputDelimited"><elementParameter name="UNIQUE_NAME" value="i1"/></node>
      <node componentName="tMap"><elementParameter name="UNIQUE_NAME" value="m1"/></node>
      <node componentName="tFileOutputDelimited"><elementParameter name="UNIQUE_NAME" value="o1"/></node>
      <connection connectorName="FLOW" source="i1" target="m1"/>
      <connection connectorName="FLOW" source="m1" target="o1"/>
      <subjob/>
    </talendfile:ProcessType>"""

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "simple.item"
        p.write_text(SIMPLE, encoding="utf-8")
        m = ti.parse_item(p)
        a = assess(m)
        simple_score = a["score"]
        assert a["signals"]["n_components"] == 3
        assert a["signals"]["n_maps"] == 1
        # Thresholds are UNCALIBRATED defaults — assert the low end of the scale,
        # not an exact bucket (that is what calibration against a real project +
        # a real Talend Audit export fixes).
        assert a["bucket"] in ("Very Simple", "Simple"), (a["score"], a["bucket"])
        assert a["calibrated"] is False
        assert a["approx_flags"]["ext_systems_approx"] is True

    # Heavy synthetic job -> should climb the buckets.
    nodes = "".join(
        f'<node componentName="tOracleInput"><elementParameter name="UNIQUE_NAME" value="n{i}"/>'
        f'<elementParameter name="QUERY" value="SELECT a FROM t{i} WHERE x = +context.y"/></node>'
        for i in range(8)
    )
    maps = "".join(
        f'<node componentName="tMap"><elementParameter name="UNIQUE_NAME" value="mm{i}"/>'
        '<nodeData xsi:type="talendmapper:MapperData">'
        '<inputTables name="a"/><inputTables name="b"/><inputTables name="c"/>'
        '<outputTables name="o"><mapperTableEntries name="x" expression="a.x"/>'
        '<mapperTableEntries name="y" expression="b.y"/></outputTables>'
        '</nodeData></node>' for i in range(4)
    )
    conns = "".join(f'<connection connectorName="ITERATE" source="n{i}" target="mm0"/>' for i in range(3))
    HEAVY = ('<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x" '
             'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
             f'{nodes}{maps}{conns}<subjob/><subjob/></talendfile:ProcessType>')
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "heavy.item"
        p.write_text(HEAVY, encoding="utf-8")
        m = ti.parse_item(p)
        a = assess(m, runjob_depth=3, ext_systems=5)
        assert a["signals"]["n_maps"] == 4
        assert a["signals"]["n_loops"] >= 3
        assert a["bucket"] in ("Moderate", "Complex", "Very Complex"), (a["score"], a["bucket"])
        assert a["score"] > simple_score  # heavier job must score strictly higher
        assert a["score"] > 20

    # Config override path (calibration simulation).
    cfg = dict(DEFAULT_CONFIG)
    cfg["config_version"] = "calibrated-v1"
    assert assess(ti.parse_item(Path(d) / "heavy.item") if False else m, config=cfg)["calibrated"] is True

    print("talend_complexity.py self-test passed")
