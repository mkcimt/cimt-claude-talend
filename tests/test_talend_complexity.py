"""Offline unit tests for talend_complexity.py — the deterministic static
complexity metric. Builds synthetic `.item` files via tempfile (xmlns:xsi is
declared on the root whenever xsi:type appears; attribute values never contain
raw double-quotes). Covers signal extraction, score monotonicity, bucket
boundaries, the calibrated flag, and the approx flags.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import talend_complexity as tc  # noqa: E402
import talend_item as ti  # noqa: E402

XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'


def _write_item(body: str, needs_xsi: bool = False) -> ti.ItemModel:
    """Wrap a node/connection body in a ProcessType root and parse it."""
    xsi = XSI if needs_xsi else ""
    item = ('<?xml version="1.0"?>'
            f'<talendfile:ProcessType xmlns:talendfile="x" {xsi}>'
            f'{body}</talendfile:ProcessType>')
    d = tempfile.mkdtemp()
    p = Path(d) / "synthetic.item"
    p.write_text(item, encoding="utf-8")
    return ti.parse_item(p)


def _node(component: str, unique: str, **params: str) -> str:
    extra = "".join(f'<elementParameter name="{k}" value="{v}"/>'
                    for k, v in params.items())
    return (f'<node componentName="{component}">'
            f'<elementParameter name="UNIQUE_NAME" value="{unique}"/>{extra}</node>')


def _tmap(unique: str, n_inputs: int, out_exprs: int) -> str:
    inputs = "".join(f'<inputTables name="in{i}"/>' for i in range(n_inputs))
    outs = "".join(f'<mapperTableEntries name="c{i}" expression="in0.c{i}"/>'
                   for i in range(out_exprs))
    return (f'<node componentName="tMap">'
            f'<elementParameter name="UNIQUE_NAME" value="{unique}"/>'
            '<nodeData xsi:type="talendmapper:MapperData">'
            f'{inputs}<outputTables name="o">{outs}</outputTables>'
            '</nodeData></node>')


# A 3-component linear job, no maps/lookups/loops.
SIMPLE_BODY = (
    _node("tFileInputDelimited", "i1")
    + _node("tMap", "m1")
    + _node("tFileOutputDelimited", "o1")
    + '<connection connectorName="FLOW" source="i1" target="m1"/>'
    + '<connection connectorName="FLOW" source="m1" target="o1"/>'
    + '<subjob/>'
)

# A heavy job: 8 source nodes (with dynamic SQL), 4 maps with 3-input lookups,
# 3 ITERATE connections (loops), two contexts via context vars, two subjobs.
_heavy_nodes = "".join(
    # Note: the SQL value uses +context to flag dynamic SQL; no raw quotes inside.
    _node("tOracleInput", f"n{i}", QUERY="SELECT a FROM t WHERE x = +context.y")
    for i in range(8)
)
_heavy_maps = "".join(_tmap(f"mm{i}", n_inputs=3, out_exprs=2) for i in range(4))
_heavy_conns = "".join(
    f'<connection connectorName="ITERATE" source="n{i}" target="mm0"/>'
    for i in range(3)
)
HEAVY_BODY = _heavy_nodes + _heavy_maps + _heavy_conns + "<subjob/><subjob/>"


class TestExtractSignals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = _write_item(HEAVY_BODY, needs_xsi=True)
        cls.sig = tc.extract_signals(cls.model)

    def test_no_parse_error(self):
        self.assertIsNone(self.model.parse_error)

    def test_n_components(self):
        # 8 sources + 4 maps = 12 active components.
        self.assertEqual(self.sig["n_components"], 12)

    def test_n_maps(self):
        self.assertEqual(self.sig["n_maps"], 4)

    def test_n_map_lookups(self):
        # Each tMap has 3 input tables -> 2 lookups; 4 maps -> 8.
        self.assertEqual(self.sig["n_map_lookups"], 8)

    def test_n_loops_from_iterate(self):
        # 3 ITERATE connections.
        self.assertEqual(self.sig["n_loops"], 3)

    def test_n_sql_dynamic(self):
        # All 8 source queries reference +context -> dynamic.
        self.assertEqual(self.sig["n_sql_dynamic"], 8)

    def test_context_vars_count(self):
        body = (
            '<context name="Default">'
            '<contextParameter name="a" value="1"/>'
            '<contextParameter name="b" value="2"/>'
            '</context>'
            + _node("tMap", "m1")
        )
        sig = tc.extract_signals(_write_item(body))
        self.assertEqual(sig["n_context_vars"], 2)


class TestScoreMonotonicity(unittest.TestCase):
    def test_heavier_scores_strictly_higher(self):
        simple = tc.assess(_write_item(SIMPLE_BODY))
        heavy = tc.assess(_write_item(HEAVY_BODY, needs_xsi=True),
                          ext_systems=5, runjob_depth=3)
        self.assertGreater(heavy["score"], simple["score"])

    def test_score_is_nonnegative(self):
        self.assertGreaterEqual(tc.score({}), 0.0)


class TestBucketBoundaries(unittest.TestCase):
    def test_default_bucket_thresholds(self):
        # Derive boundaries from DEFAULT_CONFIG so this test survives recalibration.
        buckets = tc.DEFAULT_CONFIG["buckets"]
        self.assertEqual(tc.bucket(0.0), buckets[0][0])  # lowest bucket at score 0
        prev_upper = None
        for label, upper in buckets:
            self.assertEqual(tc.bucket(upper if upper != float("inf") else 10_000.0), label
                             if upper != float("inf") else buckets[-1][0])
            if upper != float("inf"):
                self.assertEqual(tc.bucket(upper), label)            # inclusive upper bound
                self.assertNotEqual(tc.bucket(upper + 0.01), label)  # next score -> next bucket
            if prev_upper is not None:
                self.assertEqual(tc.bucket(prev_upper + 0.01), label)
            prev_upper = upper if upper != float("inf") else prev_upper
        self.assertEqual(tc.bucket(10_000.0), buckets[-1][0])


class TestAssess(unittest.TestCase):
    def test_simple_job_low_end(self):
        a = tc.assess(_write_item(SIMPLE_BODY))
        self.assertEqual(a["signals"]["n_components"], 3)
        self.assertEqual(a["signals"]["n_maps"], 1)
        self.assertIn(a["bucket"], ("Very Simple", "Simple"))
        self.assertEqual(a["provenance"], "static")

    def test_calibrated_false_for_default_config(self):
        a = tc.assess(_write_item(SIMPLE_BODY))
        self.assertFalse(a["calibrated"])
        self.assertEqual(a["config_version"], tc.DEFAULT_CONFIG["config_version"])

    def test_calibrated_true_when_config_version_calibrated(self):
        cfg = dict(tc.DEFAULT_CONFIG)
        cfg["config_version"] = "calibrated-example-v1"
        a = tc.assess(_write_item(SIMPLE_BODY), config=cfg)
        self.assertTrue(a["calibrated"])

    def test_approx_flags_set_when_not_supplied(self):
        # No ext_systems / runjob_depth passed -> both approximated single-file.
        body = _heavy_nodes + _node("tRunJob", "rj1")  # tRunJob -> runjob present
        a = tc.assess(_write_item(body))
        self.assertTrue(a["approx_flags"]["ext_systems_approx"])
        self.assertTrue(a["approx_flags"]["runjob_depth_approx"])

    def test_approx_flags_cleared_when_supplied(self):
        a = tc.assess(_write_item(SIMPLE_BODY), ext_systems=2, runjob_depth=0)
        self.assertFalse(a["approx_flags"]["ext_systems_approx"])
        self.assertFalse(a["approx_flags"]["runjob_depth_approx"])

    def test_ext_systems_approx_true_when_omitted_even_without_runjob(self):
        a = tc.assess(_write_item(SIMPLE_BODY))  # no runjob in SIMPLE_BODY
        self.assertTrue(a["approx_flags"]["ext_systems_approx"])
        # runjob_depth_approx is only set when a runjob exists.
        self.assertFalse(a["approx_flags"]["runjob_depth_approx"])


if __name__ == "__main__":
    unittest.main()
