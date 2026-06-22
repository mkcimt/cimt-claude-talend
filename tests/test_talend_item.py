"""Offline unit tests for talend_item.py — the stdlib-only `.item`/`.properties`
XMI reader. Fixtures are inline synthetic XMI strings (customer-agnostic); the
parser must never raise, degrading to a model with `parse_error` on bad input.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import talend_item as ti  # noqa: E402

# A complete, well-formed job: contexts, an active + an inactive node, a tMap
# with a lookup, a tRunJob with a compound param key, two connections, a subjob.
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
      version="0.2" purpose="Load parts from a source to a target" description="demo"/>
  <TalendProperties:ItemState xmi:id="_b" path="staging"/>
  <TalendProperties:ProcessItem xmi:id="_c" property="_a" state="_b"/>
</xmi:XMI>
"""


def _write_temp(text: str, suffix: str) -> Path:
    d = tempfile.mkdtemp()
    p = Path(d) / ("fixture" + suffix)
    p.write_text(text, encoding="utf-8")
    return p


class TestParseItem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = _write_temp(ITEM, ".item")
        cls.model = ti.parse_item(cls.path)

    def test_no_parse_error_and_root_tag(self):
        self.assertIsNone(self.model.parse_error)
        self.assertEqual(self.model.root_tag, "ProcessType")

    def test_node_count(self):
        self.assertEqual(len(self.model.nodes), 4,
                         [n.component for n in self.model.nodes])

    def test_connections(self):
        self.assertEqual(len(self.model.connections), 2)
        c0 = self.model.connections[0]
        self.assertEqual(c0.connector, "FLOW")
        self.assertEqual(c0.source, "tOracleInput_1")
        self.assertEqual(c0.target, "tMap_1")
        self.assertEqual(c0.label, "row1")
        self.assertEqual(c0.line_style, "2")

    def test_contexts_and_context_vars(self):
        self.assertEqual(set(self.model.contexts), {"Default", "prd"})
        self.assertEqual(self.model.context_vars, {"db_host", "db_name"})
        self.assertEqual(self.model.contexts["prd"]["db_name"], "PROD")

    def test_subjob_count(self):
        self.assertEqual(self.model.subjob_count, 1)

    def test_component_prefix_histogram(self):
        self.assertEqual(self.model.component_prefix_histogram().get("t"), 4)

    def test_mapper_counts(self):
        tmap = self.model.find("tMap")[0]
        self.assertIsNotNone(tmap.mapper)
        self.assertEqual(tmap.mapper.n_input_tables, 2)
        self.assertEqual(tmap.mapper.n_output_tables, 1)
        self.assertEqual(tmap.mapper.n_lookups, 1)          # inputs beyond the first
        self.assertEqual(tmap.mapper.n_output_expressions, 2)
        self.assertEqual(tmap.mapper.n_var_expressions, 1)
        self.assertEqual(tmap.mapper.n_filter_expressions, 1)


class TestActivateFiltering(unittest.TestCase):
    def test_active_nodes_excludes_deactivated(self):
        model = ti.parse_item(_write_temp(ITEM, ".item"))
        # tMSSqlOutput has ACTIVATE=false -> excluded from active_nodes.
        self.assertEqual(len(model.active_nodes()), 3)
        active_names = {n.component for n in model.active_nodes()}
        self.assertNotIn("tMSSqlOutput", active_names)
        # The node is still present in nodes (just inactive).
        deactivated = model.find("tMSSqlOutput")[0]
        self.assertFalse(deactivated.active)


class TestNodeParamSynonyms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ti.parse_item(_write_temp(ITEM, ".item"))
        cls.ora = cls.model.find("tOracleInput")[0]
        cls.rj = cls.model.find("tRunJob")[0]

    def test_exact_match(self):
        self.assertEqual(self.ora.param("HOST"), "context.db_host")
        self.assertTrue(self.ora.param("QUERY").startswith("SELECT"))

    def test_case_insensitive_match(self):
        self.assertEqual(self.ora.param("host"), "context.db_host")

    def test_synonym_fallback_first_hit_wins(self):
        # First synonym (HOSTNAME) is absent; falls through to HOST.
        self.assertEqual(self.ora.param("HOSTNAME", "HOST"), "context.db_host")

    def test_substring_match_compound_key(self):
        # PROCESS:PROCESS_TYPE_PROCESS is matched by the substring PROCESS_TYPE_PROCESS.
        self.assertEqual(self.rj.param("PROCESS_TYPE_PROCESS"), "child_job")

    def test_unresolved_when_absent(self):
        self.assertEqual(self.ora.param("DOES_NOT_EXIST"), ti.UNRESOLVED)

    def test_module_level_param_function(self):
        self.assertEqual(ti.param(self.ora, "HOST"), "context.db_host")


class TestFind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ti.parse_item(_write_temp(ITEM, ".item"))

    def test_exact_name(self):
        self.assertEqual(len(self.model.find("tMap")), 1)

    def test_prefix_glob(self):
        # tOracleInput, tMSSqlOutput -> none start with tMap except tMap itself.
        self.assertEqual(len(self.model.find("tMSSql*")), 1)

    def test_multiple_names(self):
        self.assertEqual(len(self.model.find("tMap", "tOracleInput")), 2)

    def test_no_match(self):
        self.assertEqual(self.model.find("tNope"), [])


class TestLoadProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.info = ti.load_properties(_write_temp(PROPS, ".properties"))

    def test_no_parse_error(self):
        self.assertIsNone(self.info.parse_error)

    def test_item_type(self):
        self.assertEqual(self.info.item_type, "ProcessItem")

    def test_label(self):
        self.assertEqual(self.info.label, "j_load_parts")

    def test_version(self):
        self.assertEqual(self.info.version, "0.2")

    def test_id(self):
        self.assertEqual(self.info.id, "_uuid-123")

    def test_purpose(self):
        self.assertTrue(self.info.purpose.startswith("Load parts"))

    def test_xsi_type_preferred_over_local_name(self):
        # When an item element carries an explicit xsi:type it should win.
        props = """<?xml version="1.0" encoding="UTF-8"?>
<xmi:XMI xmi:version="2.0" xmlns:xmi="http://www.omg.org/XMI"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:TalendProperties="http://www.talend.org/properties">
  <TalendProperties:Property xmi:id="_a" id="_x" label="lbl" version="0.1"/>
  <TalendProperties:Item xmi:id="_c" xsi:type="TalendProperties:JobletProcessItem" property="_a"/>
</xmi:XMI>
"""
        info = ti.load_properties(_write_temp(props, ".properties"))
        self.assertEqual(info.item_type, "TalendProperties:JobletProcessItem")


class TestGracefulDegradation(unittest.TestCase):
    def test_malformed_item_sets_parse_error_no_raise(self):
        bad = _write_temp("<not-xml", ".item")
        model = ti.parse_item(bad)          # must not raise
        self.assertIsNotNone(model.parse_error)
        self.assertEqual(model.nodes, [])
        self.assertEqual(model.connections, [])
        self.assertEqual(model.context_vars, set())

    def test_malformed_properties_sets_parse_error_no_raise(self):
        bad = _write_temp("<not-xml", ".properties")
        info = ti.load_properties(bad)      # must not raise
        self.assertIsNotNone(info.parse_error)
        self.assertEqual(info.item_type, "")
        self.assertEqual(info.label, "")

    def test_missing_file_degrades(self):
        info = ti.load_properties(Path(tempfile.mkdtemp()) / "nope.properties")
        self.assertIsNotNone(info.parse_error)
        model = ti.parse_item(Path(tempfile.mkdtemp()) / "nope.item")
        self.assertIsNotNone(model.parse_error)
        self.assertEqual(model.nodes, [])


if __name__ == "__main__":
    unittest.main()
