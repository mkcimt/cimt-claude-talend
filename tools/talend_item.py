"""
talend_item.py — stdlib-only, namespace-tolerant reader for Talend `.item` +
`.properties` XMI pairs.

The shared low-level layer the project-intake analyzer builds on. `.item` files
are EMF/XMI exported by Talend Studio (see
`knowledge/mechanics/item-file-format.md`). This module is deliberately
*defensive*: it never raises on a malformed file or node — it degrades to a
best-effort model and records a `parse_error` instead of crashing. That is a
hard requirement, because the projects we analyse often have no naming
conventions and may contain partially-broken artifacts.

Design choice — capture everything, interpret later. We store *all*
`elementParameter` values as a plain `name -> value` dict on each node rather
than hard-coding the handful of parameter keys we think we need. Exact XMI
parameter-key names (HOST / DBNAME / FILENAME / QUERY …) are convention-based
and cannot be verified without a real `.item` sample, so downstream code
(`component_catalog.py`) pattern-matches a synonym set against the full dict.
This is the "trusted name layer vs. param-key hardening" two-stage contract.

Public surface:
- load_properties(path) -> PropertiesInfo   (item_type, label, id, version, purpose)
- parse_item(path) -> ItemModel             (nodes, connections, contexts, root tag)
- ItemModel.find(component)                 (nodes whose componentName matches)
- param(node, *synonyms)                    (first matching elementParameter value)

`item_type` and component classification are intentionally NOT done here — that
is `talend_discovery.py` / `component_catalog.py`. This module only extracts
raw structure.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

# The XML-Schema-instance `type` attribute carries the EMF concrete type, e.g.
# xsi:type="talendmapper:MapperData" on a tMap's <nodeData>.
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

UNRESOLVED = "(unresolved)"


def _local(tag: str) -> str:
    """Strip the `{namespace}` prefix ElementTree prepends, leaving the local name."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xsi_type(el: ET.Element) -> str:
    """Return the xsi:type of an element (namespace-tolerant), or ''."""
    t = el.get(_XSI_TYPE)
    if t:
        return t
    for k, v in el.attrib.items():
        if _local(k) == "type":
            return v
    return ""


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class MapperData:
    """Extracted shape of a tMap / tXMLMap / tHMap node's mapping table."""

    n_input_tables: int = 0
    n_output_tables: int = 0
    n_output_expressions: int = 0
    n_var_expressions: int = 0
    n_filter_expressions: int = 0
    lookup_modes: list[str] = field(default_factory=list)   # lookupMode per lookup input table

    @property
    def n_lookups(self) -> int:
        # Input tables beyond the first are lookup joins.
        return max(0, self.n_input_tables - 1)

    @property
    def n_reload_lookups(self) -> int:
        # Reload-at-each-row lookups — a classic tMap performance pitfall.
        return sum(1 for m in self.lookup_modes if m in ("RELOAD", "CACHE_OR_RELOAD"))


@dataclass
class Node:
    """One Talend component (`<node componentName=…>`)."""

    component: str
    unique_name: str
    active: bool = True
    params: dict[str, str] = field(default_factory=dict)
    param_tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    mapper: Optional[MapperData] = None

    def param(self, *synonyms: str) -> str:
        """First matching simple-parameter value, or UNRESOLVED.

        Matching is exact first, then case-insensitive, then substring — so a
        caller can pass canonical keys (``"HOST"``) and still hit vendor
        variants (``"HOSTNAME"``) without hard-coding every spelling.
        """
        return param(self, *synonyms)


@dataclass
class Connection:
    """One `<connection>` edge between two components."""

    connector: str          # FLOW / FILTER / REJECT / ITERATE / RUN_IF / ON_* ...
    source: str
    target: str
    label: str = ""
    line_style: str = ""


@dataclass
class ItemModel:
    """Parsed `.item` file. Always returned, even on parse failure (see parse_error)."""

    root_tag: str = ""
    nodes: list[Node] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    contexts: dict[str, dict[str, str]] = field(default_factory=dict)  # env -> {var: value}
    context_vars: set[str] = field(default_factory=set)               # distinct names
    subjob_count: int = 0
    parse_error: Optional[str] = None

    def active_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.active]

    def find(self, *components: str) -> list[Node]:
        """Nodes whose componentName matches any of the given names or `prefix*` globs."""
        out: list[Node] = []
        for n in self.nodes:
            for c in components:
                if _component_matches(n.component, c):
                    out.append(n)
                    break
        return out

    def component_prefix_histogram(self) -> dict[str, int]:
        """Counts of the leading-letter component family (`t` vs `c`) — route detection signal."""
        hist: dict[str, int] = {}
        for n in self.nodes:
            if not n.component:
                continue
            key = n.component[0]
            hist[key] = hist.get(key, 0) + 1
        return hist


@dataclass
class PropertiesInfo:
    """Identity + type discriminator read from a `.properties` XMI file."""

    item_type: str = ""     # raw xsi:type or item element local-name (e.g. "ProcessItem")
    label: str = ""         # human name — USE THIS, not the filename
    id: str = ""            # stable id, survives version bumps
    version: str = ""       # Talend item version (e.g. "0.1")
    purpose: str = ""
    description: str = ""
    parse_error: Optional[str] = None


# --------------------------------------------------------------------------- #
# Matching helpers
# --------------------------------------------------------------------------- #
def _component_matches(name: str, pattern: str) -> bool:
    """`tOracleInput` matches `tOracle*` and `tOracleInput`; case-sensitive on the stem."""
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern


def param(node: Node, *synonyms: str) -> str:
    """First matching elementParameter value on `node`, or UNRESOLVED.

    Tries, in order: exact key, case-insensitive key, case-insensitive substring.
    """
    p = node.params
    # exact
    for s in synonyms:
        if s in p and p[s] != "":
            return p[s]
    # case-insensitive exact
    lower = {k.lower(): v for k, v in p.items()}
    for s in synonyms:
        v = lower.get(s.lower())
        if v not in (None, ""):
            return v
    # substring (handles compound keys like "PROCESS:PROCESS_TYPE_PROCESS")
    for s in synonyms:
        sl = s.lower()
        for k, v in p.items():
            if sl in k.lower() and v != "":
                return v
    return UNRESOLVED


# --------------------------------------------------------------------------- #
# .properties parsing
# --------------------------------------------------------------------------- #
def load_properties(path: Path | str) -> PropertiesInfo:
    """Read a Talend `.properties` XMI file for type + identity.

    The file pairs a `<TalendProperties:Property>` (label/id/version/purpose)
    with an item element whose local-name / xsi:type encodes the artifact type
    (`ProcessItem`, `JobletProcessItem`, `RouteItem`, `ServiceItem`, …).
    Element names and xsi:type strings are `[VALIDATE]` against a real project —
    this reader is tolerant of both spellings.
    """
    info = PropertiesInfo()
    p = Path(path)
    try:
        root = ET.parse(p).getroot()
    except Exception as exc:  # noqa: BLE001 — never crash on a broken file
        info.parse_error = f"{type(exc).__name__}: {exc}"
        return info

    for el in root.iter():
        ln = _local(el.tag)
        if ln == "Property":
            info.label = el.get("label", "") or info.label
            info.id = el.get("id", "") or info.id
            info.version = el.get("version", "") or info.version
            info.purpose = el.get("purpose", "") or info.purpose
            info.description = el.get("description", "") or info.description
        elif ln == "ItemState":
            continue  # path/locked flags — not a type discriminator
        elif ln.endswith("Item") and not info.item_type:
            # Prefer the explicit xsi:type, fall back to the element local-name.
            info.item_type = _xsi_type(el) or ln

    return info


# --------------------------------------------------------------------------- #
# .item parsing
# --------------------------------------------------------------------------- #
def _parse_element_params(node_el: ET.Element) -> tuple[dict[str, str], dict[str, list[dict[str, str]]], Optional[MapperData]]:
    """Pull simple params, table params, and any tMap data out of a `<node>`."""
    params: dict[str, str] = {}
    tables: dict[str, list[dict[str, str]]] = {}
    mapper: Optional[MapperData] = None

    for child in node_el:
        ln = _local(child.tag)
        if ln == "elementParameter":
            name = child.get("name") or ""
            if not name:
                continue
            # Nested <elementValue> children => a table-type parameter.
            ev = [c for c in child if _local(c.tag) == "elementValue"]
            if ev:
                tables[name] = [dict(c.attrib) for c in ev]
            else:
                params[name] = child.get("value", "")
        elif ln == "nodeData" and "MapperData" in _xsi_type(child):
            mapper = _parse_mapper(child)

    return params, tables, mapper


def _parse_mapper(node_data: ET.Element) -> MapperData:
    """Count tables / expressions inside a tMap `<nodeData>`."""
    m = MapperData()
    for el in node_data.iter():
        ln = _local(el.tag)
        if ln == "inputTables":
            is_first = (m.n_input_tables == 0)   # the first input table is the main flow, not a lookup
            m.n_input_tables += 1
            if el.get("expressionFilter"):
                m.n_filter_expressions += 1
            mode = el.get("lookupMode")
            if mode and not is_first:
                m.lookup_modes.append(mode)
        elif ln == "outputTables":
            m.n_output_tables += 1
            if el.get("expressionFilter"):
                m.n_filter_expressions += 1
        elif ln == "varTables":
            for e in el:
                if _local(e.tag) == "mapperTableEntries" and e.get("expression"):
                    m.n_var_expressions += 1
    # Output expressions: mapperTableEntries carrying a non-empty expression,
    # but only inside output tables (an empty expression on an input column is a
    # normal declaration — see knowledge/mechanics/item-file-format.md).
    for out in (e for e in node_data.iter() if _local(e.tag) == "outputTables"):
        for entry in out:
            if _local(entry.tag) == "mapperTableEntries" and entry.get("expression"):
                m.n_output_expressions += 1
    return m


def parse_item(path: Path | str) -> ItemModel:
    """Parse a `.item` file into an ItemModel. Never raises."""
    model = ItemModel()
    p = Path(path)
    try:
        root = ET.parse(p).getroot()
    except Exception as exc:  # noqa: BLE001
        model.parse_error = f"{type(exc).__name__}: {exc}"
        return model

    model.root_tag = _local(root.tag)

    for el in root.iter():
        ln = _local(el.tag)
        if ln == "node":
            try:
                params, tables, mapper = _parse_element_params(el)
                comp = el.get("componentName", "") or ""
                unique = params.get("UNIQUE_NAME", "") or el.get("componentName", "")
                active = (params.get("ACTIVATE", "true").lower() != "false")
                model.nodes.append(
                    Node(component=comp, unique_name=unique, active=active,
                         params=params, param_tables=tables, mapper=mapper)
                )
            except Exception:  # noqa: BLE001 — one bad node must not kill the parse
                continue
        elif ln == "connection":
            model.connections.append(
                Connection(
                    connector=el.get("connectorName", ""),
                    source=el.get("source", ""),
                    target=el.get("target", ""),
                    label=el.get("label", ""),
                    line_style=el.get("lineStyle", ""),
                )
            )
        elif ln == "context":
            env = el.get("name", "") or "Default"
            cvars = model.contexts.setdefault(env, {})
            for cp in el:
                if _local(cp.tag) == "contextParameter":
                    vname = cp.get("name", "")
                    if vname:
                        cvars[vname] = cp.get("value", "")
                        model.context_vars.add(vname)
        elif ln == "subjob":
            model.subjob_count += 1

    return model


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import tempfile

    ITEM = """<?xml version="1.0" encoding="UTF-8"?>
<talendfile:ProcessType xmi:version="2.0"
    xmlns:xmi="http://www.omg.org/XMI"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:talendfile="platform:/resource/org.talend.model/model/TalendFile.xsd">
  <context confirmationNeeded="false" name="Default">
    <contextParameter name="db_host" type="id_String" value="localhost"/>
    <contextParameter name="db_name" type="id_String" value="STAGING"/>
  </context>
  <context confirmationNeeded="false" name="prd">
    <contextParameter name="db_host" type="id_String" value="prd-host"/>
    <contextParameter name="db_name" type="id_String" value="PROD"/>
  </context>
  <node componentName="tOracleInput">
    <elementParameter field="TEXT" name="UNIQUE_NAME" show="false" value="tOracleInput_1"/>
    <elementParameter field="CHECK" name="ACTIVATE" value="true"/>
    <elementParameter field="TEXT" name="HOST" value="context.db_host"/>
    <elementParameter field="MEMO_SQL" name="QUERY" value="SELECT id, name FROM parts"/>
  </node>
  <node componentName="tMap">
    <elementParameter field="TEXT" name="UNIQUE_NAME" show="false" value="tMap_1"/>
    <nodeData xsi:type="talendmapper:MapperData">
      <inputTables name="row1">
        <mapperTableEntries name="id" expression="row1.id"/>
        <mapperTableEntries name="name"/>
      </inputTables>
      <inputTables name="lookup1" lookupMode="LOAD_ONCE">
        <mapperTableEntries name="ref" expression="lookup1.ref"/>
      </inputTables>
      <varTables name="Var">
        <mapperTableEntries name="v1" expression="StringHandling.UPCASE(row1.name)"/>
      </varTables>
      <outputTables name="out1" expressionFilter="row1.id != null">
        <mapperTableEntries name="id" expression="row1.id"/>
        <mapperTableEntries name="up" expression="Var.v1"/>
      </outputTables>
    </nodeData>
  </node>
  <node componentName="tMSSqlOutput">
    <elementParameter field="TEXT" name="UNIQUE_NAME" show="false" value="tMSSqlOutput_1"/>
    <elementParameter field="CHECK" name="ACTIVATE" value="false"/>
    <elementParameter field="TEXT" name="TABLE" value="dbo.parts"/>
  </node>
  <node componentName="tRunJob">
    <elementParameter field="TEXT" name="UNIQUE_NAME" show="false" value="tRunJob_1"/>
    <elementParameter field="PROCESS_TYPE" name="PROCESS:PROCESS_TYPE_PROCESS" value="child_job"/>
  </node>
  <connection connectorName="FLOW" label="row1" lineStyle="2" source="tOracleInput_1" target="tMap_1"/>
  <connection connectorName="FLOW" label="out1" lineStyle="2" source="tMap_1" target="tMSSqlOutput_1"/>
  <subjob/>
</talendfile:ProcessType>
"""

    PROPS = """<?xml version="1.0" encoding="UTF-8"?>
<xmi:XMI xmi:version="2.0" xmlns:xmi="http://www.omg.org/XMI"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:TalendProperties="http://www.talend.org/properties">
  <TalendProperties:Property xmi:id="_a" id="_uuid-123" label="j_load_parts"
      version="0.2" purpose="Load parts from Oracle to SQL Server" description="demo"/>
  <TalendProperties:ItemState xmi:id="_b" path="staging"/>
  <TalendProperties:ProcessItem xmi:id="_c" property="_a" state="_b"/>
</xmi:XMI>
"""

    with tempfile.TemporaryDirectory() as d:
        ip = Path(d) / "j_load_parts_0.2.item"
        pp = Path(d) / "j_load_parts_0.2.properties"
        ip.write_text(ITEM, encoding="utf-8")
        pp.write_text(PROPS, encoding="utf-8")

        m = parse_item(ip)
        assert m.parse_error is None, m.parse_error
        assert m.root_tag == "ProcessType", m.root_tag
        assert len(m.nodes) == 4, [n.component for n in m.nodes]
        assert len(m.active_nodes()) == 3  # tMSSqlOutput is ACTIVATE=false
        assert m.subjob_count == 1
        assert len(m.connections) == 2
        assert m.context_vars == {"db_host", "db_name"}
        assert set(m.contexts) == {"Default", "prd"}

        ora = m.find("tOracleInput")[0]
        assert ora.param("QUERY").startswith("SELECT")
        assert ora.param("HOST") == "context.db_host"
        assert ora.param("HOSTNAME", "HOST") == "context.db_host"  # synonym fallback

        tmap = m.find("tMap")[0]
        assert tmap.mapper is not None
        assert tmap.mapper.n_input_tables == 2
        assert tmap.mapper.n_lookups == 1
        assert tmap.mapper.n_output_expressions == 2
        assert tmap.mapper.n_var_expressions == 1
        assert tmap.mapper.n_filter_expressions == 1

        rj = m.find("tRunJob")[0]
        assert rj.param("PROCESS_TYPE_PROCESS") == "child_job"  # substring match

        hist = m.component_prefix_histogram()
        assert hist.get("t") == 4

        info = load_properties(pp)
        assert info.parse_error is None, info.parse_error
        assert info.item_type == "ProcessItem", info.item_type
        assert info.label == "j_load_parts"
        assert info.version == "0.2"
        assert info.id == "_uuid-123"
        assert info.purpose.startswith("Load parts")

        # Robustness: a broken file must not raise.
        bad = Path(d) / "broken.item"
        bad.write_text("<not-xml", encoding="utf-8")
        bm = parse_item(bad)
        assert bm.parse_error is not None
        assert bm.nodes == []

    print("talend_item.py self-test passed")
