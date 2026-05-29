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


class TestDispatchTable(unittest.TestCase):
    def test_all_dispatch_keys_have_handlers(self):
        for key, fn in ops.DISPATCH.items():
            self.assertTrue(callable(fn), f"{key} handler not callable")

    def test_info_verbs_present(self):
        self.assertIn(("task", "info"), ops.DISPATCH)
        self.assertIn(("dqrule", "info"), ops.DISPATCH)


if __name__ == "__main__":
    unittest.main()
