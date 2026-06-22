"""End-to-end offline test for project_intake.analyze() against a synthetic,
customer-agnostic Talend project fixture (hand-written — no real customer data).

Verifies: artifact discovery + version dedup, type classification, the
component->system registry, complexity assessment, interface clustering,
gap collection, graceful degradation on a malformed .item, and the
provenance-on-every-fact contract.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import project_intake as pi  # noqa: E402

XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'

PROPS = """<?xml version="1.0" encoding="UTF-8"?>
<xmi:XMI xmi:version="2.0" xmlns:xmi="http://www.omg.org/XMI"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:TalendProperties="http://www.talend.org/properties">
  <TalendProperties:Property xmi:id="_a" id="{id}" label="{label}" version="{ver}" purpose="{purpose}"/>
  <TalendProperties:{item} xmi:id="_c" property="_a"/>
</xmi:XMI>
"""


def _write(root: Path, folder: str, stem: str, ver: str, item_token: str,
           nodes: str = "", purpose: str = "demo", broken: bool = False) -> None:
    fd = root / folder
    fd.mkdir(parents=True, exist_ok=True)
    item = ("<not-xml" if broken else
            f'<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x" {XSI}>'
            f'{nodes}</talendfile:ProcessType>')
    (fd / f"{stem}_{ver}.item").write_text(item, encoding="utf-8")
    (fd / f"{stem}_{ver}.properties").write_text(
        PROPS.format(id=f"_{stem}", label=stem, ver=ver, purpose=purpose, item=item_token),
        encoding="utf-8")


def _node(component: str, unique: str, **params: str) -> str:
    extra = "".join(f'<elementParameter name="{k}" value="{v}"/>' for k, v in params.items())
    return (f'<node componentName="{component}">'
            f'<elementParameter name="UNIQUE_NAME" value="{unique}"/>{extra}</node>')


def build_fixture(root: Path) -> None:
    # Interface i100: a top job that calls a worker (a real call edge).
    _write(root, "process/orders", "j_orders_top", "0.1", "ProcessItem",
           nodes=_node("tOracleInput", "ora1", QUERY="SELECT id FROM orders")
                 + _node("tMap", "m1")
                 + _node("tRunJob", "rj1", **{"PROCESS:PROCESS_TYPE_PROCESS": "j_orders_work"}))
    # Two stem versions — highest (0.2) wins.
    _write(root, "process/orders", "j_orders_work", "0.1", "ProcessItem",
           nodes=_node("tMap", "m2"))
    _write(root, "process/orders", "j_orders_work", "0.2", "ProcessItem",
           nodes=_node("tMap", "m2")
                 + _node("tMSSqlOutput", "sql1", TABLE="dbo.orders")
                 + _node("tFileOutputDelimited", "f1", FILENAME="/tmp/out.csv"))
    # A route (Camel components -> route detection + ActiveMQ system).
    _write(root, "routes", "r_dispatch", "0.1", "RouteItem",
           nodes=_node("cMessagingEndpoint", "mep1", URI="activemq:queue:orders")
                 + _node("cJMS", "jms1"))
    # A joblet, and a job that embeds it + an unknown component.
    _write(root, "joblets", "jl_audit", "0.1", "JobletProcessItem")
    _write(root, "process/misc", "j_uses_joblet", "0.1", "ProcessItem",
           nodes=_node("jl_audit", "jl_1") + _node("tWeirdCustomThing", "w1"))
    # A repository DB connection (metadata, not executable).
    _write(root, "metadata/connections", "conn_oracle", "0.1", "DatabaseConnectionItem")
    # A malformed .item -> must degrade, not crash.
    _write(root, "process/broken", "j_broken", "0.1", "ProcessItem", broken=True)
    # An artifact in an archive folder -> excluded.
    _write(root, "process/a__archive", "j_retired", "0.1", "ProcessItem")


class TestProjectIntake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        build_fixture(root)
        cls.doc = pi.analyze(root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_top_level_shape(self):
        d = self.doc
        for key in ("schema_version", "generated_at", "project", "systems",
                    "artifacts", "interfaces", "tmc", "gaps", "manual"):
            self.assertIn(key, d)
        self.assertEqual(d["schema_version"], pi.SCHEMA_VERSION)

    def test_counts_and_version_dedup(self):
        counts = self.doc["project"]["artifact_counts"]
        # top, work, uses_joblet, broken = 4 jobs; archive excluded.
        self.assertEqual(counts["jobs"], 4, counts)
        self.assertEqual(counts["routes"], 1)
        self.assertEqual(counts["joblets"], 1)
        self.assertEqual(counts["connections"], 1)
        labels = {a["name"] for a in self.doc["artifacts"]}
        self.assertNotIn("j_retired", labels)  # archive excluded
        work = next(a for a in self.doc["artifacts"] if a["name"] == "j_orders_work")
        self.assertEqual(work["item_version"], "0.2")
        self.assertEqual(work["superseded_versions"], ["0.1"])

    def test_route_classified_from_camel(self):
        r = next(a for a in self.doc["artifacts"] if a["name"] == "r_dispatch")
        self.assertEqual(r["type"], "route")

    def test_systems_registry(self):
        techs = {s["technology"] for s in self.doc["systems"]}
        self.assertIn("Oracle", techs)
        self.assertIn("MS SQL Server", techs)
        self.assertIn("ActiveMQ", techs)
        self.assertIn("local file", techs)
        # Oracle host is context-driven -> unresolved.
        ora = next(s for s in self.doc["systems"] if s["technology"] == "Oracle")
        self.assertFalse(ora["resolved"])

    def test_read_write_direction(self):
        work = next(a for a in self.doc["artifacts"] if a["name"] == "j_orders_work")
        sysmap = {s["system_id"]: s for s in self.doc["systems"]}
        write_techs = {sysmap[i]["technology"] for i in work["systems_write"]}
        self.assertIn("MS SQL Server", write_techs)
        self.assertIn("local file", write_techs)

    def test_call_edge_and_interface(self):
        top = next(a for a in self.doc["artifacts"] if a["name"] == "j_orders_top")
        self.assertTrue(any(c["target_name"] == "j_orders_work" for c in top["calls"]))
        # The two i100 jobs cluster into one high-confidence interface.
        iface = next(i for i in self.doc["interfaces"]
                     if any(self._name(m) == "j_orders_top" for m in i["member_artifacts"]))
        member_names = {self._name(m) for m in iface["member_artifacts"]}
        self.assertEqual(member_names, {"j_orders_top", "j_orders_work"})
        self.assertEqual(iface["confidence"], "high")
        self.assertEqual([self._name(e) for e in iface["entry_points"]], ["j_orders_top"])
        self.assertEqual(iface["status"], "proposed")

    def test_complexity_present_and_estimated(self):
        for a in self.doc["artifacts"]:
            if a["type"] in ("job", "route"):
                self.assertIsNotNone(a["complexity"])
                self.assertIn(a["complexity"]["bucket"],
                              ("Very Simple", "Simple", "Moderate", "Complex", "Very Complex"))
                self.assertFalse(a["complexity"]["calibrated"])

    def test_graceful_degradation(self):
        # The malformed job is still listed; its parse error is recorded.
        self.assertTrue(any(a["name"] == "j_broken" for a in self.doc["artifacts"]))
        self.assertTrue(any(e["artifact"] == "j_broken"
                            for e in self.doc["project"]["parse_errors"]))

    def test_gaps_collected(self):
        kinds = {g["kind"] for g in self.doc["gaps"]}
        self.assertIn("unresolved_connection", kinds)
        self.assertIn("unknown_component", kinds)
        for g in self.doc["gaps"]:
            self.assertEqual(g["provenance"], "manual")
            self.assertTrue(g["gap_id"].startswith("gap-"))

    def test_tmc_block_reserved_empty(self):
        tmc = self.doc["tmc"]
        self.assertFalse(tmc["enriched"])
        self.assertEqual(tmc["tasks"], [])
        self.assertEqual(tmc["plans"], [])

    def test_provenance_on_every_fact(self):
        for a in self.doc["artifacts"]:
            self.assertEqual(a["provenance"], "static")
        for s in self.doc["systems"]:
            self.assertEqual(s["provenance"], "static")
        for i in self.doc["interfaces"]:
            self.assertEqual(i["provenance"], "static")

    def _name(self, artifact_id: str) -> str:
        for a in self.doc["artifacts"]:
            if a["artifact_id"] == artifact_id:
                return a["name"]
        return artifact_id


if __name__ == "__main__":
    unittest.main(verbosity=2)
