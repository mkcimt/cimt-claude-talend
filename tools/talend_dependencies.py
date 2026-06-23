"""
talend_dependencies.py — extract external library / JAR / driver dependencies from
a parsed `.item`, and flag the things that break Talend upgrades.

The single biggest predictor of upgrade breakage is hard-referenced external
libraries — above all the *same* library pinned to *different* versions across a
project (version drift), and non-standard custom jars. These survive in the
`.item` as DB driver jars (`DRIVER_JAR`), `tLibraryLoad` libraries, and bare
`*.jar` references. This module surfaces them deterministically so an upgrade
estimate can price them in.

Validated against a real project: DB driver jars (`DRIVER_JAR` /
`DRIVER_JAR_IMPLICIT_CONTEXT`), `tLibraryLoad` (`LIBRARY`), and `*.jar` literals
in any parameter — including the same driver pinned to two versions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import talend_item as ti  # noqa: E402

_JAR_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._+-]*\.jar)")
# name<sep>version.jar  ->  base + version  (vendordb_V3R1.jar, vendordb-4.1.jar, lib-1.2.3.jar)
_VER_RE = re.compile(r"^(?P<base>.+?)[-_](?P<ver>[vV]?\d[\w.]*)\.jar$")
_DRIVER_HINTS = ("DRIVER",)
_LIBRARY_HINTS = ("LIBRARY", "LIBPATH", "JAVA_LIBRARY_PATH")


def parse_jar(jar: str) -> tuple[str, str]:
    """`vendordb_V3R1.jar` -> ('vendordb', 'V3R1'); `ojdbc8.jar` -> ('ojdbc8', '')."""
    m = _VER_RE.match(jar)
    if m:
        return m.group("base"), m.group("ver")
    return (jar[:-4] if jar.endswith(".jar") else jar), ""


def _kind(param_name: str, component: str) -> str:
    if component == "tLibraryLoad":
        return "library_load"
    up = param_name.upper()
    if any(h in up for h in _DRIVER_HINTS):
        return "driver_jar"
    if any(h in up for h in _LIBRARY_HINTS):
        return "library"
    return "jar_ref"


def extract_dependencies(model: ti.ItemModel) -> list[dict]:
    """All distinct external jar references in one artifact, with provenance."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for n in model.active_nodes():
        for pname, pval in n.params.items():
            if not pval or ".jar" not in pval:
                continue
            for jar in _JAR_RE.findall(pval):
                key = (jar, n.unique_name)
                if key in seen:
                    continue
                seen.add(key)
                base, ver = parse_jar(jar)
                out.append({
                    "jar": jar, "lib_base": base, "version": ver,
                    "kind": _kind(pname, n.component),
                    "source_component": n.component, "unique_name": n.unique_name,
                    "provenance": "static",
                })
    return out


def summarize(all_deps: list[dict]) -> dict:
    """Project-level dependency + upgrade-risk view over every artifact's deps.

    `all_deps` is the flat list of dep records (each enriched by the caller with
    an `artifact` name). Flags version drift (same lib, multiple versions) and
    version-pinned jars — the upgrade-risk signals.
    """
    by_lib: dict[str, set[str]] = {}
    distinct_jars: set[str] = set()
    pinned: set[str] = set()
    for d in all_deps:
        distinct_jars.add(d["jar"])
        # Track an "(unversioned)" sentinel too, so an unpinned + pinned pair of the
        # same library (e.g. ojdbc.jar + ojdbc-19.3.jar) trips drift — also an
        # upgrade risk, not just two different pinned versions.
        by_lib.setdefault(d["lib_base"], set()).add(d["version"] or "(unversioned)")
        if d["version"]:
            pinned.add(d["jar"])

    version_drift = [
        {"lib_base": base, "versions": sorted(vers),
         "jars": sorted(j for j in distinct_jars if parse_jar(j)[0] == base)}
        for base, vers in by_lib.items() if len(vers) > 1
    ]
    version_drift.sort(key=lambda x: x["lib_base"])

    flags: list[str] = []
    if version_drift:
        flags.append(f"version drift: {len(version_drift)} lib(s) referenced in >1 version "
                     f"(breaks upgrades): {', '.join(d['lib_base'] for d in version_drift)}")
    if pinned:
        flags.append(f"{len(pinned)} version-pinned jar(s) hard-referenced")

    return {
        "distinct_jars": sorted(distinct_jars),
        "distinct_libs": sorted(by_lib),
        "total_refs": len(all_deps),
        "version_drift": version_drift,
        "version_pinned_jars": sorted(pinned),
        "upgrade_risk_flags": flags,
        "provenance": "static",
    }


if __name__ == "__main__":
    import tempfile

    ITEM = """<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x">
      <node componentName="tAS400Input">
        <elementParameter name="UNIQUE_NAME" value="db1"/>
        <elementParameter name="DRIVER_JAR" value="vendordb_V3R1.jar"/>
      </node>
      <node componentName="tAS400Connection">
        <elementParameter name="UNIQUE_NAME" value="db2"/>
        <elementParameter name="DRIVER_JAR_IMPLICIT_CONTEXT" value="vendordb-4.1.jar"/>
      </node>
      <node componentName="tLibraryLoad">
        <elementParameter name="UNIQUE_NAME" value="lib1"/>
        <elementParameter name="LIBRARY" value="custom-utils-1.2.3.jar"/>
      </node>
      <node componentName="tJava">
        <elementParameter name="UNIQUE_NAME" value="j1"/>
        <elementParameter name="CODE" value="// no jars here"/>
      </node>
    </talendfile:ProcessType>"""

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.item"
        p.write_text(ITEM, encoding="utf-8")
        deps = extract_dependencies(ti.parse_item(p))
        jars = {x["jar"] for x in deps}
        assert jars == {"vendordb_V3R1.jar", "vendordb-4.1.jar", "custom-utils-1.2.3.jar"}, jars
        kinds = {x["jar"]: x["kind"] for x in deps}
        assert kinds["vendordb_V3R1.jar"] == "driver_jar"
        assert kinds["custom-utils-1.2.3.jar"] == "library_load"

        assert parse_jar("vendordb_V3R1.jar") == ("vendordb", "V3R1")
        assert parse_jar("vendordb-4.1.jar") == ("vendordb", "4.1")
        assert parse_jar("custom-utils-1.2.3.jar") == ("custom-utils", "1.2.3")
        assert parse_jar("ojdbc8.jar") == ("ojdbc8", "")

        summ = summarize([dict(x, artifact="x") for x in deps])
        drift = {d["lib_base"]: d["versions"] for d in summ["version_drift"]}
        assert "vendordb" in drift and drift["vendordb"] == ["4.1", "V3R1"], drift
        assert len(summ["distinct_jars"]) == 3
        assert summ["upgrade_risk_flags"], "expected upgrade-risk flags"

    print("talend_dependencies.py self-test passed")
