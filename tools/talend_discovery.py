"""
talend_discovery.py — walk a Talend project tree and classify every artifact,
without trusting names.

Produces the artifact skeletons the analyzer fills in. Three things happen here:

1. **Find & pair** every `.item` with its `.properties`, excluding noise
   (`.screenshot`, `a__archive/`, `*.lock`).
2. **Version-select** — `name_0.1.item` / `name_0.2.item` are Studio-internal
   versions (NOT git). Group by stem, highest wins; older pairs are reported as
   superseded, not analysed (see `knowledge/mechanics/item-file-format.md`).
3. **Classify** — type comes from the `.properties` item element (authoritative),
   corroborated by folder and by the `.item` component-prefix histogram
   (all `t*` ⇒ job, dominant `c*` ⇒ route). Disagreement is recorded in
   `non_standard_flags` rather than guessed away — exactly the messy-project case.

Detection strings (`ProcessItem`, `RouteItem`, …) are `[VALIDATE]` against a real
ESB project; the prefix-histogram fallback is the robust safety net.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import talend_item as ti  # noqa: E402

_VERSION_RE = re.compile(r"^(?P<stem>.+)_(?P<major>\d+)\.(?P<minor>\d+)$")

# Path segments that mark retired / non-functional / transient content.
_EXCLUDE_SEGMENTS = {"a__archive", "recycle_bin", "temp"}
_EXCLUDE_SUFFIXES = ("__archive",)
_EXCLUDE_NAMES = {"archive", "archived", "obsolete", "_old", "old"}

# .properties item-element token (after stripping ns prefix) -> canonical type.
_TYPE_MAP: dict[str, str] = {
    "ProcessItem": "job",
    "JobletProcessItem": "joblet",
    "JobletItem": "joblet",
    "RouteItem": "route",
    "RouteProcessItem": "route",
    "CamelProcessItem": "route",
    "RouteletItem": "routelet",
    "RouteletProcessItem": "routelet",
    "ServiceItem": "service",
    "SparkProcessItem": "spark_job",
    "SparkStreamingProcessItem": "spark_streaming_job",
    "MapReduceProcessItem": "mr_job",
    "StormProcessItem": "storm_job",
    "BigDataProcessItem": "spark_job",
    "ContextItem": "context",
    "RoutineItem": "routine",
    "BeanItem": "bean",
    "SQLPatternItem": "sql_pattern",
}
# Top-level folder -> canonical type (corroboration only).
_FOLDER_TYPE: dict[str, str] = {
    "process": "job",
    "process_mr": "spark_job",
    "process_storm": "storm_job",
    "routes": "route",
    "routelets": "routelet",
    "services": "service",
    "joblets": "joblet",
    "routines": "routine",
    "code": "routine",
    "beans": "bean",
    "metadata": "metadata",
    "sqlpatterns": "sql_pattern",
    "sqltemplate": "sql_pattern",
}


def _canon_token(raw: str) -> str:
    """`TalendProcess:ProcessItem` / `{ns}ProcessItem` -> `ProcessItem`."""
    return raw.split(":")[-1].split("}")[-1] if raw else ""


@dataclass
class ArtifactRef:
    """One on-disk artifact, the active version selected."""

    stem: str
    item_path: Path
    properties_path: Optional[Path]
    version: tuple[int, int]
    top_folder: str = ""
    rel_dir: str = ""
    # Filled by classify_artifact():
    type: str = "unknown"
    item_type_raw: str = ""
    label: str = ""
    id: str = ""
    purpose: str = ""
    type_signals: dict = field(default_factory=dict)
    non_standard_flags: list[str] = field(default_factory=list)
    superseded_versions: list[str] = field(default_factory=list)


def is_excluded(path: Path) -> bool:
    """True if a path is under a retired/archive folder or is a lock file."""
    if path.suffix == ".lock" or path.name.endswith(".lock"):
        return True
    for part in path.parts:
        low = part.lower()
        if low in _EXCLUDE_SEGMENTS or low in _EXCLUDE_NAMES:
            return True
        if any(low.endswith(suf) for suf in _EXCLUDE_SUFFIXES):
            return True
    return False


def _split_version(item_path: Path) -> tuple[str, tuple[int, int]]:
    """`j_load_parts_0.2.item` -> ('j_load_parts', (0, 2)). No version -> (name, (-1,-1))."""
    name = item_path.name
    if name.endswith(".item"):
        name = name[: -len(".item")]
    m = _VERSION_RE.match(name)
    if m:
        return m.group("stem"), (int(m.group("major")), int(m.group("minor")))
    return name, (-1, -1)


def scan_project(root: Path | str) -> list[ArtifactRef]:
    """Find, pair, and version-select all artifacts under `root`."""
    root = Path(root)
    # stem-key -> list of (version, item_path)
    groups: dict[tuple[str, str], list[tuple[tuple[int, int], Path]]] = {}
    for item_path in root.rglob("*.item"):
        if is_excluded(item_path):
            continue
        stem, version = _split_version(item_path)
        rel_dir = str(item_path.parent.relative_to(root)) if item_path.parent != root else ""
        key = (rel_dir, stem)
        groups.setdefault(key, []).append((version, item_path))

    refs: list[ArtifactRef] = []
    for (rel_dir, stem), pairs in groups.items():
        pairs.sort(key=lambda pv: pv[0])
        version, item_path = pairs[-1]  # highest version is active
        superseded = [f"{v[0]}.{v[1]}" for v, _ in pairs[:-1]]
        props_path = item_path.with_suffix(".properties")
        if not props_path.exists():
            props_path = None
        top_folder = rel_dir.split("/")[0] if rel_dir else ""
        refs.append(
            ArtifactRef(
                stem=stem, item_path=item_path, properties_path=props_path,
                version=version, top_folder=top_folder, rel_dir=rel_dir,
                superseded_versions=superseded,
            )
        )
    refs.sort(key=lambda r: (r.top_folder, r.rel_dir, r.stem))
    return refs


def classify_artifact(ref: ArtifactRef, item_model: Optional[ti.ItemModel] = None) -> ArtifactRef:
    """Set ref.type / label / signals / flags from .properties + folder + .item.

    Mutates and returns `ref`. Never raises.
    """
    props = ti.load_properties(ref.properties_path) if ref.properties_path else ti.PropertiesInfo()
    ref.item_type_raw = props.item_type
    ref.label = props.label or ref.stem
    ref.id = props.id
    ref.purpose = props.purpose

    token = _canon_token(props.item_type)
    type_from_props = _TYPE_MAP.get(token, "")
    if not type_from_props and "DataServiceREST" in token:
        type_from_props = "service"          # REST data-service contract (the API definition)
    elif not type_from_props and token.endswith("ConnectionItem"):
        type_from_props = "connection"
    elif not type_from_props and token.endswith("Item") and token not in _TYPE_MAP:
        type_from_props = ""  # leave unknown; corroborate below

    type_from_folder = _FOLDER_TYPE.get(ref.top_folder.lower(), "")

    prefix_hist = item_model.component_prefix_histogram() if item_model else {}
    root_tag = item_model.root_tag if item_model else ""
    type_from_item = ""
    if prefix_hist:
        c = prefix_hist.get("c", 0)
        t = prefix_hist.get("t", 0)
        if c > t and c > 0:
            type_from_item = "route"
        elif t > 0:
            type_from_item = "job"

    # Precedence: properties (authoritative) -> folder -> .item histogram.
    final = type_from_props or type_from_folder or type_from_item or "unknown"
    ref.type = final

    # Flag disagreements (the messy-project signal).
    flags: list[str] = []
    if type_from_props and type_from_folder and type_from_props != type_from_folder:
        # connection/context live under metadata/ — that's expected, not a conflict.
        if not (type_from_folder == "metadata"):
            flags.append(f"type/folder mismatch: props={type_from_props} folder={type_from_folder}")
    if final in ("job", "route") and type_from_item and final != type_from_item:
        flags.append(f"type/component-prefix mismatch: {final} vs {type_from_item}")
    if not type_from_props and final != "unknown":
        flags.append(f"type inferred from {'folder' if type_from_folder else 'components'} (no .properties type)")
    if final == "unknown":
        flags.append("artifact type unresolved")
    ref.non_standard_flags = flags
    ref.type_signals = {
        "folder": ref.top_folder, "xsi_type": props.item_type or "",
        "root_element": root_tag, "prefix_hist": prefix_hist,
        "type_from_props": type_from_props, "type_from_folder": type_from_folder,
        "type_from_item": type_from_item,
    }
    return ref


# Types that are executable artifacts (counted as "interfaces" candidates).
EXECUTABLE_TYPES = {"job", "route", "routelet", "joblet", "service",
                    "spark_job", "spark_streaming_job", "mr_job", "storm_job"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="List & classify Talend artifacts in a project tree.")
    p.add_argument("project_path", help="path to the Talend project root")
    p.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    p.add_argument("--classify", action="store_true",
                   help="parse each .item for full classification (slower)")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project_path)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    refs = scan_project(root)
    rows = []
    for r in refs:
        model = ti.parse_item(r.item_path) if args.classify else None
        classify_artifact(r, model)
        rows.append({
            "type": r.type, "label": r.label, "version": f"{r.version[0]}.{r.version[1]}",
            "folder": r.rel_dir, "flags": r.non_standard_flags,
        })
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        from collections import Counter
        by_type = Counter(r["type"] for r in rows)
        for r in rows:
            flag = "  ⚠ " + "; ".join(r["flags"]) if r["flags"] else ""
            print(f"{r['type']:>20}  {r['label']}  ({r['version']}){flag}")
        print("\n--- counts ---")
        for t, n in sorted(by_type.items()):
            print(f"{t:>20}: {n}")
    return 0


if __name__ == "__main__":
    import tempfile

    PROPS_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<xmi:XMI xmi:version="2.0" xmlns:xmi="http://www.omg.org/XMI"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:TalendProperties="http://www.talend.org/properties">
  <TalendProperties:Property xmi:id="_a" id="{id}" label="{label}" version="{ver}" purpose="{purpose}"/>
  <TalendProperties:{item} xmi:id="_c" property="_a"/>
</xmi:XMI>
"""
    ITEM_T = '<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x">{nodes}</talendfile:ProcessType>'

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        def write(folder, stem, ver, item_token, nodes="", purpose="p"):
            fd = root / folder
            fd.mkdir(parents=True, exist_ok=True)
            (fd / f"{stem}_{ver}.item").write_text(
                ITEM_T.format(nodes=nodes), encoding="utf-8")
            (fd / f"{stem}_{ver}.properties").write_text(
                PROPS_TMPL.format(id=f"_{stem}", label=stem, ver=ver,
                                  purpose=purpose, item=item_token), encoding="utf-8")

        write("process/staging", "j_load", "0.1", "ProcessItem",
              nodes='<node componentName="tOracleInput"/><node componentName="tMap"/>')
        write("process/staging", "j_load", "0.2", "ProcessItem",   # newer version
              nodes='<node componentName="tOracleInput"/><node componentName="tMap"/>')
        write("routes", "r_dispatch", "0.1", "RouteItem",
              nodes='<node componentName="cMessagingEndpoint"/><node componentName="cJMS"/>')
        write("joblets", "jl_helper", "0.1", "JobletProcessItem")
        write("metadata/connections", "conn_oracle", "0.1", "DatabaseConnectionItem")
        # An artifact in an archive folder must be skipped.
        write("process/a__archive", "j_old", "0.1", "ProcessItem")

        refs = scan_project(root)
        labels = {r.stem for r in refs}
        assert "j_old" not in labels, "archive artifact not excluded"
        assert len(refs) == 4, [r.stem for r in refs]  # j_load(dedup), r_dispatch, jl_helper, conn_oracle

        by_stem = {r.stem: r for r in refs}
        j = by_stem["j_load"]
        assert j.version == (0, 2), j.version
        assert j.superseded_versions == ["0.1"], j.superseded_versions
        classify_artifact(j, ti.parse_item(j.item_path))
        assert j.type == "job", j.type
        assert j.label == "j_load"

        r = by_stem["r_dispatch"]
        classify_artifact(r, ti.parse_item(r.item_path))
        assert r.type == "route", (r.type, r.type_signals)

        conn = by_stem["conn_oracle"]
        classify_artifact(conn, ti.parse_item(conn.item_path))
        assert conn.type == "connection", conn.type

        jl = by_stem["jl_helper"]
        classify_artifact(jl, ti.parse_item(jl.item_path))
        assert jl.type == "joblet", jl.type

        print("talend_discovery.py self-test passed")
