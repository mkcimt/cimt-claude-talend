"""Offline unit tests for tds_ops pure helpers + arg parsing (no network)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import tds_ops as ops  # noqa: E402


class TestFilterByName(unittest.TestCase):
    items = [
        {"name": "demo_product", "displayName": "Demo - Product"},
        {"name": "customer_data_model", "displayName": "Customer Data Model"},
    ]

    def test_no_filter_returns_all(self):
        self.assertEqual(len(ops.filter_by_name(self.items, None)), 2)

    def test_match_on_name(self):
        out = ops.filter_by_name(self.items, "product")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "demo_product")

    def test_match_on_display_name_case_insensitive(self):
        out = ops.filter_by_name(self.items, "CUSTOMER")
        self.assertEqual(len(out), 1)

    def test_no_match_exits(self):
        with self.assertRaises(SystemExit):
            ops.filter_by_name(self.items, "zzz")


class TestParser(unittest.TestCase):
    def setUp(self):
        self.p = ops.build_parser()

    def test_datamodel_list(self):
        a = self.p.parse_args(["datamodel", "list", "--name", "x", "--json"])
        self.assertEqual((a.object, a.action), ("datamodel", "list"))
        self.assertEqual(a.name, "x")
        self.assertTrue(a.json)

    def test_campaign_get(self):
        a = self.p.parse_args(["campaign", "get", "c123"])
        self.assertEqual((a.object, a.action), ("campaign", "get"))
        self.assertEqual(a.name, "c123")

    def test_campaign_list_all_flag(self):
        a = self.p.parse_args(["campaign", "list", "--all"])
        self.assertTrue(a.all)

    def test_semantic_get_key(self):
        a = self.p.parse_args(["semantic", "get", "EMAIL"])
        self.assertEqual(a.key, "EMAIL")

    def test_task_info(self):
        a = self.p.parse_args(["task", "info"])
        self.assertEqual((a.object, a.action), ("task", "info"))


class TestWriteParsing(unittest.TestCase):
    def setUp(self):
        self.p = ops.build_parser()

    def test_datamodel_create_demo(self):
        a = self.p.parse_args(["datamodel", "create", "--demo", "--name", "x", "--apply"])
        self.assertTrue(a.demo and a.apply and a.name == "x")

    def test_create_defaults_to_dry_run(self):
        a = self.p.parse_args(["datamodel", "create", "--demo"])
        self.assertFalse(a.apply)

    def test_campaign_delete(self):
        a = self.p.parse_args(["campaign", "delete", "cimt-demo-1", "--apply"])
        self.assertEqual((a.object, a.action, a.name), ("campaign", "delete", "cimt-demo-1"))


class TestDemoBuilders(unittest.TestCase):
    def test_demo_datamodel_shape(self):
        m = ops.build_demo_datamodel("cimt_demo_1")
        self.assertEqual(m["name"], "cimt_demo_1")
        self.assertTrue(all("name" in f and "type" in f for f in m["fields"]))

    def test_demo_campaign_shape(self):
        c = ops.build_demo_campaign("cimt-demo-1", "cimt_demo_1", "u@x.io", version=2,
                                    display_name="D")
        camp = c["campaign"]
        self.assertEqual(camp["name"], "cimt-demo-1")
        self.assertEqual(camp["taskType"], "RESOLUTION")
        self.assertEqual(camp["owners"], ["u@x.io"])
        self.assertEqual(camp["schemaRef"], {"namespace": "org.talend.schema",
                                             "name": "cimt_demo_1", "version": 2,
                                             "displayName": "D"})
        self.assertEqual(c["participants"]["Supervisor"], ["u@x.io"])
        self.assertEqual([s["name"] for s in camp["workflow"]["states"]],
                         ["New", "To validate", "Resolved"])

    def test_demo_name_separators(self):
        self.assertIn("_", ops.demo_name("_"))
        self.assertIn("-", ops.demo_name("-"))
        self.assertNotIn("_", ops.demo_name("-"))

    def test_demo_semantic_regex_shape(self):
        s = ops.build_demo_semantic_regex("CIMT_DEMO_X")
        self.assertEqual(s["type"], "REGEX")
        self.assertEqual(s["name"], "CIMT_DEMO_X")
        self.assertIn("patternString", s["regEx"]["validator"])


class TestSemanticParsing(unittest.TestCase):
    def setUp(self):
        self.p = ops.build_parser()

    def test_semantic_create_demo(self):
        a = self.p.parse_args(["semantic", "create", "--demo", "--name", "S", "--apply"])
        self.assertTrue(a.demo and a.apply and a.name == "S")

    def test_semantic_delete(self):
        a = self.p.parse_args(["semantic", "delete", "abc123", "--apply"])
        self.assertEqual((a.object, a.action, a.id), ("semantic", "delete", "abc123"))


class TestTaskParsing(unittest.TestCase):
    def setUp(self):
        self.p = ops.build_parser()

    def test_task_list(self):
        a = self.p.parse_args(["task", "list", "mm-demo", "--state", "New", "--invalid"])
        self.assertEqual((a.object, a.action, a.campaign), ("task", "list", "mm-demo"))
        self.assertEqual(a.state, "New")
        self.assertTrue(a.invalid)

    def test_task_create_defaults(self):
        a = self.p.parse_args(["task", "create", "c1", "--file", "r.json"])
        self.assertEqual(a.type, "RESOLUTION")
        self.assertFalse(a.apply)        # dry-run by default
        self.assertFalse(a.unassigned)

    def test_task_create_assignee(self):
        a = self.p.parse_args(["task", "create", "c1", "--file", "-",
                               "--assignee", "u@x.io", "--apply"])
        self.assertEqual(a.assignee, "u@x.io")
        self.assertTrue(a.apply)


class TestTaskAssigneeResolution(unittest.TestCase):
    class _Args:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def _client(self, email):
        c = ops.tc.TdsClient(cfg={"tds.base_url": "https://x", "tds.token": "t",
                                  "tds.user_email": email})
        return c

    def test_default_from_config(self):
        a = self._Args(assignee=None, unassigned=False)
        self.assertEqual(ops._task_assignee(self._client("me@x.io"), a), "me@x.io")

    def test_override(self):
        a = self._Args(assignee="other@x.io", unassigned=False)
        self.assertEqual(ops._task_assignee(self._client("me@x.io"), a), "other@x.io")

    def test_unassigned(self):
        a = self._Args(assignee=None, unassigned=True)
        self.assertIsNone(ops._task_assignee(self._client("me@x.io"), a))


class TestDispatchTable(unittest.TestCase):
    def test_all_dispatch_keys_have_handlers(self):
        for key, fn in ops.DISPATCH.items():
            self.assertTrue(callable(fn), f"{key} handler not callable")

    def test_task_verbs_present(self):
        for v in ("list", "get", "create", "info"):
            self.assertIn(("task", v), ops.DISPATCH)


if __name__ == "__main__":
    unittest.main()
