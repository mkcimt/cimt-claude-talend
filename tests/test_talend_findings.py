"""Tests for the deterministic static-review findings catalog (Schicht 1)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import talend_findings as fm  # noqa: E402
import talend_item as ti  # noqa: E402

ITEM = """<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <node componentName="tOracleInput">
    <elementParameter name="UNIQUE_NAME" value="in1"/>
    <elementParameter name="QUERY" value="SELECT * FROM orders WHERE n LIKE '%x' AND id = +context.id"/>
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
  </node>
  <node componentName="tOracleInput">
    <elementParameter name="UNIQUE_NAME" value="dead1"/>
    <elementParameter name="ACTIVATE" value="false"/>
  </node>
</talendfile:ProcessType>"""


def _model(body):
    d = tempfile.mkdtemp()
    p = Path(d) / "x.item"
    p.write_text(body, encoding="utf-8")
    return ti.parse_item(p)


class TestFindings(unittest.TestCase):
    def setUp(self):
        self.artifact = {"type": "job", "components": [
            {"direction": "read", "family": "DB"}, {"direction": "write", "family": "DB"}]}
        self.findings = fm.extract(_model(ITEM), self.artifact)
        self.cats = {f["category"] for f in self.findings}

    def test_detects_reload_lookup(self):
        self.assertIn("lookup_reload", self.cats)
        rl = next(f for f in self.findings if f["category"] == "lookup_reload")
        self.assertEqual(rl["location"], "m1")
        self.assertEqual(rl["severity"], "perf")

    def test_detects_sql_smells(self):
        self.assertIn("sql_select_star", self.cats)
        self.assertIn("sql_leading_wildcard", self.cats)
        self.assertIn("sql_dynamic", self.cats)

    def test_detects_inactive_and_missing_error_handling(self):
        self.assertIn("inactive_components", self.cats)
        self.assertIn("no_error_handling", self.cats)

    def test_no_error_handling_skipped_when_handler_present(self):
        body = ('<?xml version="1.0"?><talendfile:ProcessType xmlns:talendfile="x">'
                '<node componentName="tMSSqlOutput"><elementParameter name="UNIQUE_NAME" value="o"/></node>'
                '<node componentName="tDie"><elementParameter name="UNIQUE_NAME" value="d"/></node>'
                '</talendfile:ProcessType>')
        f = fm.extract(_model(body), self.artifact)
        self.assertFalse(any(x["category"] == "no_error_handling" for x in f))

    def test_no_error_handling_skipped_when_no_external_write(self):
        f = fm.extract(_model(ITEM), {"type": "job", "components": [{"direction": "read", "family": "File"}]})
        self.assertFalse(any(x["category"] == "no_error_handling" for x in f))

    def test_every_finding_has_provenance_and_severity(self):
        for f in self.findings:
            self.assertEqual(f["provenance"], "static")
            self.assertIn(f["severity"], ("bug", "perf", "smell", "dead_code"))

    def test_summarize_rollup(self):
        s = fm.summarize([dict(f, artifact="x") for f in self.findings])
        self.assertEqual(s["total"], len(self.findings))
        self.assertEqual(sum(s["by_severity"].values()), len(self.findings))
        self.assertEqual(sum(s["by_category"].values()), len(self.findings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
