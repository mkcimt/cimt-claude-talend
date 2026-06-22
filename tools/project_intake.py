#!/usr/bin/env python3
"""
project_intake.py — the offline Talend project analyzer (phase 1 of /project-intake).

Walks a Talend Studio project on disk and produces the **canonical intake JSON
document**: the single source of truth that the Excel renderer (phase 2), TMC
enrichment (phase 3) and manual review (phase 4) all build on. This tool is
stdlib-only and never needs credentials or a running TMC — it works on a plain
Git checkout.

Golden rules (see `knowledge/patterns/project-intake.md`):
- Every fact carries `provenance ∈ {static, tmc, manual}`. This tool only emits
  `static` facts; it reserves empty `tmc` / `manual` / `gaps` structures.
- Unresolved-but-known facts become the literal string `"(unresolved)"` and are
  also recorded in `gaps[]` so a later phase can harden them.
- Never crash on a messy project: unknown components, broken `.item` files and
  missing `.properties` all degrade gracefully and are reported, not fatal.

Usage:
    project_intake.py <project-path> [--out intake.json] [--pretty]
    project_intake.py <project-path> --summary      # human-readable counts only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import component_catalog as cat  # noqa: E402
import talend_complexity as cx  # noqa: E402
import talend_discovery as disc  # noqa: E402
import talend_item as ti  # noqa: E402
import talend_topology as topo  # noqa: E402

SCHEMA_VERSION = "1.0"
UNRESOLVED = ti.UNRESOLVED

# NOTE: no bare "PROCESS" — it would substring-match sibling params like
# PROCESS:PROCESS_TYPE_VERSION/_CONTEXT and pull a wrong call target.
_CALL_TARGET_KEYS = ("PROCESS_TYPE_PROCESS", "SELECTED_JOB_NAME", "JOB")

# Artifact types whose `.item` is NOT XMI (routines/beans hold Java source,
# SQL patterns hold SQL text). We must not XML-parse these — doing so is an
# expected non-error, so they are classified from `.properties` only.
NON_XML_TYPES = {"routine", "bean", "sql_pattern"}


def _sys_id(family: str, technology: str, identity_key: str) -> str:
    h = hashlib.sha1(f"{family}|{technology}|{identity_key}".encode("utf-8")).hexdigest()[:8]
    return f"sys-{h}"


def _identity_key(identity: dict) -> str:
    """Stable dedup discriminator for a system: the first locator string, else ''.

    Keeps the raw value even when it is a `context.*` reference, so two jobs that
    target different context variables stay distinct systems. Whether that locator
    counts as *resolved* is decided separately (see `_locator_resolved`).
    """
    for k in ("host", "uri", "endpoint", "bucket_or_queue_or_topic"):
        v = identity.get(k)
        if v and v != UNRESOLVED:
            return v
    return ""


def _locator_resolved(value: str) -> bool:
    """A locator is only *resolved* if it is a real value, not a context/global ref.

    `context.db_host` / `((String)globalMap.get(...))` mean the actual host is
    unknown until a context value is supplied — so it must surface as a gap.
    """
    if not value or value == UNRESOLVED:
        return False
    low = value.lower()
    return not (low.startswith("context.") or "globalmap" in low or value.startswith("+"))


def _artifact_id(ref: disc.ArtifactRef) -> str:
    if ref.id:
        return ref.id
    h = hashlib.sha1(str(ref.item_path).encode("utf-8")).hexdigest()[:8]
    return f"art-{h}"


def _read_project_descriptor(root: Path) -> tuple[str, str]:
    """Best-effort name + productVersion from the project's talend.project file."""
    desc = root / "talend.project"
    if not desc.exists():
        return UNRESOLVED, UNRESOLVED
    try:
        el = ti.ET.parse(desc).getroot()
    except Exception:  # noqa: BLE001
        return UNRESOLVED, UNRESOLVED
    name = ver = ""
    for e in el.iter():
        name = e.get("technicalLabel") or e.get("label") or name
        ver = e.get("productVersion") or ver
    return (name or UNRESOLVED), (ver or UNRESOLVED)


def _call_targets(model: ti.ItemModel) -> list[str]:
    out: list[str] = []
    for n in model.active_nodes():
        if n.component in cat.CALL_COMPONENTS:
            tgt = n.param(*_CALL_TARGET_KEYS)
            if tgt and tgt != UNRESOLVED and tgt not in out:
                out.append(tgt)
    return out


def _normalize_call_target(value: str) -> str:
    """tRunJob stores its target as ``PROJECT:_repositoryId`` (the called job's EMF
    id), not its label. Return the bare id for resolution; fall back to the raw
    value (older Studio versions store a plain job label)."""
    if value and ":" in value:
        return value.split(":", 1)[1]
    return value


def _repo_connection_refs(model: ti.ItemModel) -> list[str]:
    """Best-effort repository-connection ids referenced by the job (clustering signal)."""
    refs: list[str] = []
    for n in model.active_nodes():
        for k, v in n.params.items():
            if "REPOSITORY" in k.upper() and v and v.lower() not in ("true", "false", ""):
                if v not in refs:
                    refs.append(v)
    return refs


def analyze(project_path: Path | str, config: dict = cx.DEFAULT_CONFIG) -> dict:
    """Analyze a Talend project and return the canonical intake document (static phase)."""
    root = Path(project_path)
    refs = disc.scan_project(root)

    joblet_labels: set[str] = set()
    # First pass over .properties only to learn joblet labels (cheap classification).
    for r in refs:
        disc.classify_artifact(r, None)
        if r.type == "joblet":
            joblet_labels.add(r.label)

    # --- Pass 1: parse + per-artifact raw extraction -----------------------
    artifacts: list[dict] = []
    topo_nodes: list[topo.ArtifactNode] = []
    raw_components: list[dict] = []   # (family, technology, identity, direction) for the registry
    parse_errors: list[dict] = []

    for r in refs:
        if r.type in NON_XML_TYPES:
            model = ti.ItemModel()  # Java/SQL source — not XMI; classify from .properties only.
        else:
            model = ti.parse_item(r.item_path)
            if model.parse_error:
                parse_errors.append({"artifact": r.label, "type": r.type,
                                     "error": model.parse_error})
        disc.classify_artifact(r, model)

        aid = _artifact_id(r)
        comp_records: list[dict] = []

        for node in model.active_nodes():
            # A node whose name is a known joblet is an internal sub-flow invocation,
            # not an external system — recorded separately in joblets_used.
            if node.component in joblet_labels:
                continue
            info = cat.classify_component(node.component, node.params)
            if info["is_internal"]:
                continue
            identity = cat.extract_identity(node.params)
            objects = cat.extract_objects(node.params)
            rec = {
                "unique_name": node.unique_name,
                "component": node.component,
                "family": info["family"],
                "technology": info["technology"],
                "direction": info["direction"],
                "confidence": info["confidence"],
                "resolved": info["resolved"],
                "identity": identity,
                "objects": objects,
            }
            comp_records.append(rec)
            raw_components.append({"artifact_id": aid, **rec})

        call_targets = _call_targets(model)
        repo_conns = _repo_connection_refs(model)
        joblets_used = sorted({n.component for n in model.active_nodes()
                               if n.component in joblet_labels})

        artifacts.append({
            "artifact_id": aid,
            "name": r.label,
            "type": r.type,
            "type_signals": r.type_signals,
            "path": str(r.item_path.relative_to(root)),
            "item_version": f"{r.version[0]}.{r.version[1]}",
            "superseded_versions": r.superseded_versions,
            "purpose": r.purpose,
            "complexity": None,            # filled in pass 2
            "systems_read": [],            # system_ids, filled after registry
            "systems_write": [],
            "systems_connection": [],
            "calls": [{"target_name": t, "target_artifact_id": UNRESOLVED, "via": "tRunJob",
                       "provenance": "static"} for t in call_targets],
            "context_group_ids": [],
            "context_vars": [{"name": v, "provenance": "static"} for v in sorted(model.context_vars)],
            "repo_connection_ids": repo_conns,
            "joblets_used": joblets_used,
            "rest_contract_ref": None,
            "components": comp_records,
            "tmc_task": None,
            "tmc_execution_stats": None,
            "non_standard_flags": r.non_standard_flags,
            "provenance": "static",
            "_model": model,              # transient, stripped before output
        })
        topo_nodes.append(topo.ArtifactNode(
            id=aid, name=r.label, type=r.type, rel_dir=r.rel_dir,
            call_targets=[_normalize_call_target(t) for t in call_targets],
            context_groups=[], repo_connections=repo_conns,
            joblets=joblets_used,
        ))

    # --- Systems registry: dedup distinct external endpoints ----------------
    systems = build_systems_registry(raw_components)
    sysid_lookup = systems["_lookup"]
    systems_list = systems["systems"]

    # Assign system_ids back to each artifact + component.
    for a in artifacts:
        read_ids, write_ids, conn_ids = [], [], []
        for rec in a["components"]:
            key = (rec["family"], rec["technology"], _identity_key(rec["identity"]))
            sid = sysid_lookup.get(key)
            rec["system_id"] = sid
            if not sid:
                continue
            # "both" (REST/HTTP/SOAP/ELT clients) reads AND writes the system.
            direction = rec["direction"]
            targets = ([read_ids, write_ids] if direction == "both"
                       else [{"read": read_ids, "write": write_ids,
                              "connection": conn_ids}.get(direction, read_ids)])
            for target in targets:
                if sid not in target:
                    target.append(sid)
        a["systems_read"] = read_ids
        a["systems_write"] = write_ids
        a["systems_connection"] = conn_ids

    # --- Call graph + complexity (pass 2) -----------------------------------
    call_graph = topo.build_call_graph(topo_nodes)
    depths = topo.longest_downstream_depths(call_graph)
    # resolve call target artifact ids (target is PROJECT:_id -> normalize -> id;
    # relabel target_name to the human job name once resolved)
    name_index = call_graph["name_index"]
    id_to_label = {a["artifact_id"]: a["name"] for a in artifacts}
    for a in artifacts:
        for c in a["calls"]:
            norm = _normalize_call_target(c["target_name"])
            tid = name_index.get(norm) or name_index.get(c["target_name"], UNRESOLVED)
            c["target_artifact_id"] = tid
            if tid in id_to_label:
                c["target_name"] = id_to_label[tid]

    for a in artifacts:
        model = a["_model"]
        ext = len(set(a["systems_read"]) | set(a["systems_write"]) | set(a["systems_connection"]))
        a["complexity"] = cx.assess(
            model, artifact_type=a["type"], config=config,
            ext_systems=ext, runjob_depth=depths.get(a["artifact_id"], 0),
        )

    # --- Interfaces (logical clusters) --------------------------------------
    cluster_graph = topo.build_cluster_graph(topo_nodes, call_graph)
    interfaces = topo.propose_interfaces(topo_nodes, call_graph, cluster_graph)
    by_id = {a["artifact_id"]: a for a in artifacts}
    for iface in interfaces:
        touched: set[str] = set()
        for m in iface["member_artifacts"]:
            a = by_id.get(m)
            if a:
                touched |= set(a["systems_read"]) | set(a["systems_write"]) | set(a["systems_connection"])
        iface["systems_touched"] = sorted(touched)

    # --- Strip transient model handles --------------------------------------
    for a in artifacts:
        a.pop("_model", None)

    # --- Project meta + counts ----------------------------------------------
    name, product_version = _read_project_descriptor(root)
    counts = {
        "jobs": sum(1 for a in artifacts if a["type"] == "job"),
        "routes": sum(1 for a in artifacts if a["type"] == "route"),
        "routelets": sum(1 for a in artifacts if a["type"] == "routelet"),
        "joblets": sum(1 for a in artifacts if a["type"] == "joblet"),
        "services": sum(1 for a in artifacts if a["type"] == "service"),
        "bigdata_jobs": sum(1 for a in artifacts if a["type"] in
                            ("spark_job", "spark_streaming_job", "mr_job", "storm_job")),
        "beans": sum(1 for a in artifacts if a["type"] == "bean"),
        "routines": sum(1 for a in artifacts if a["type"] == "routine"),
        "sql_patterns": sum(1 for a in artifacts if a["type"] == "sql_pattern"),
        "connections": sum(1 for a in artifacts if a["type"] == "connection"),
        "contexts": sum(1 for a in artifacts if a["type"] == "context"),
        "unknown": sum(1 for a in artifacts if a["type"] == "unknown"),
    }

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": {"tool": "project_intake.py", "version": SCHEMA_VERSION,
                      "config_version": config.get("config_version", "")},
        "project": {
            "name": name, "product_version": product_version,
            "scanned_path": str(root.resolve()),
            "artifact_counts": counts,
            "non_standard_flags": sorted({f for a in artifacts for f in a["non_standard_flags"]}),
            "parse_errors": parse_errors,
        },
        "environments": [],
        "infrastructure": {"tmc_region": None, "workspaces": [], "engines": [],
                           "run_profiles": [], "manual_notes": []},
        "systems": systems_list,
        "artifacts": artifacts,
        "interfaces": interfaces,
        "tmc": {"enriched": False, "enriched_at": None, "region": None,
                "tasks": [], "plans": [], "execution_stats": [], "component_metrics": []},
        "gaps": [],
        "manual": {"interface_renames": {}, "system_overrides": {}, "notes": []},
    }
    doc["gaps"] = collect_gaps(doc, call_graph, refs)
    return doc


def build_systems_registry(raw_components: list[dict]) -> dict:
    """Dedup distinct external endpoints into the systems[] registry.

    Unresolved endpoints of the same (family, technology) collapse to one system
    (honest: we cannot tell two unresolved Oracle hosts apart) and are marked
    `resolved=False`; resolved endpoints split by their locator.
    """
    systems: dict[tuple[str, str, str], dict] = {}
    lookup: dict[tuple[str, str, str], str] = {}
    for rec in raw_components:
        family, tech = rec["family"], rec["technology"]
        ident = rec["identity"]
        ikey = _identity_key(ident)
        key = (family, tech, ikey)
        sid = lookup.get(key)
        if sid is None:
            sid = _sys_id(family, tech, ikey)
            lookup[key] = sid
            systems[key] = {
                "system_id": sid, "family": family, "technology": tech,
                "identity": {k: ident.get(k, UNRESOLVED) for k in
                             ("host", "port", "database", "schema", "uri", "endpoint",
                              "bucket_or_queue_or_topic")},
                "objects": [], "confidence": rec["confidence"],
                "resolved": _locator_resolved(ikey), "provenance": "static", "evidence": [],
            }
        s = systems[key]
        for o in rec.get("objects", []):
            if o not in s["objects"]:
                s["objects"].append(o)
        if len(s["evidence"]) < 25:
            s["evidence"].append({"artifact_id": rec["artifact_id"],
                                  "node_unique_name": rec["unique_name"],
                                  "component": rec["component"]})
    ordered = sorted(systems.values(), key=lambda s: (s["family"], s["technology"], s["system_id"]))
    return {"systems": ordered, "_lookup": lookup}


def collect_gaps(doc: dict, call_graph: dict, refs: list[disc.ArtifactRef]) -> list[dict]:
    """Everything the static pass could not resolve — the phase-4 worklist."""
    gaps: list[dict] = []

    def add(kind: str, ref: dict, description: str, question: str) -> None:
        gaps.append({
            "gap_id": f"gap-{len(gaps) + 1:04d}", "kind": kind, "ref": ref,
            "description": description, "suggested_question": question,
            "resolution": None, "provenance": "manual",
        })

    for s in doc["systems"]:
        if not s["resolved"] and s["technology"] != "local file":
            add("unresolved_connection", {"system_id": s["system_id"]},
                f"{s['technology']} ({s['family']}) endpoint is context-driven; host unresolved.",
                f"What is the real host/endpoint for {s['technology']} ({s['system_id']})?")
        if s["technology"] == "unknown":
            add("unknown_component", {"system_id": s["system_id"]},
                f"Unrecognised {s['family']} component(s) — technology could not be classified.",
                f"What system do the components behind {s['system_id']} talk to?")

    for src, tgt in call_graph.get("unresolved", []):
        add("runjob_target_missing", {"artifact_id": src},
            f"tRunJob/cTalendJob target '{tgt}' not found among scanned artifacts.",
            f"Where does '{tgt}' live (external project / deleted / dynamic)?")

    for iface in doc["interfaces"]:
        if iface["ambiguous_members"]:
            add("ambiguous_cluster", {"interface_id": iface["interface_id"]},
                f"Members {iface['ambiguous_members']} could belong to more than one interface.",
                "Confirm which logical interface these artifacts belong to.")

    for r in refs:
        if r.type == "unknown":
            add("needs_human", {"artifact_id": _artifact_id(r)},
                f"Artifact '{r.label}' type could not be determined.",
                f"What kind of artifact is '{r.label}'?")

    return gaps


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Offline Talend project intake analyzer (phase 1).")
    p.add_argument("project_path", help="path to the Talend project root")
    p.add_argument("--out", help="write canonical JSON to this file (default: stdout)")
    p.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    p.add_argument("--summary", action="store_true", help="print human-readable counts, no JSON")
    return p


def _print_summary(doc: dict) -> None:
    p = doc["project"]
    print(f"Project: {p['name']}  (Talend {p['product_version']})")
    print(f"Scanned: {p['scanned_path']}")
    print("\nArtifact counts:")
    for k, v in p["artifact_counts"].items():
        if v:
            print(f"  {k:>14}: {v}")
    print(f"\nSystems (distinct external endpoints): {len(doc['systems'])}")
    for s in doc["systems"]:
        mark = "" if s["resolved"] else "  (unresolved)"
        print(f"  {s['family']:>12} / {s['technology']}{mark}")
    print(f"\nProposed interfaces: {len(doc['interfaces'])}")
    print(f"Gaps to resolve:     {len(doc['gaps'])}")
    if p["parse_errors"]:
        print(f"Parse errors:        {len(p['parse_errors'])}")
    # Complexity histogram.
    from collections import Counter
    hist = Counter(a["complexity"]["bucket"] for a in doc["artifacts"]
                   if a["complexity"] and a["type"] in disc.EXECUTABLE_TYPES)
    if hist:
        print("\nComplexity (estimated, uncalibrated):")
        for b in ("Very Simple", "Simple", "Moderate", "Complex", "Very Complex"):
            if hist.get(b):
                print(f"  {b:>14}: {hist[b]}")


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project_path)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    doc = analyze(root)
    if args.summary:
        _print_summary(doc)
        return 0
    text = json.dumps(doc, indent=2 if args.pretty else None, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}  ({len(doc['artifacts'])} artifacts, "
              f"{len(doc['systems'])} systems, {len(doc['interfaces'])} interfaces, "
              f"{len(doc['gaps'])} gaps)", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
