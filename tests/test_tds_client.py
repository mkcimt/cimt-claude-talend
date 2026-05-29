"""Offline unit tests for tds_client (no network)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import tds_client as tc  # noqa: E402


class TestBaseUrl(unittest.TestCase):
    def test_explicit_base_url_wins(self):
        self.assertEqual(
            tc.base_url({"tds.base_url": "https://tds.eu.cloud.talend.com/"}),
            "https://tds.eu.cloud.talend.com",
        )

    def test_region_template(self):
        self.assertEqual(
            tc.base_url({"tds.region": "us"}),
            "https://tds.us.cloud.talend.com",
        )

    def test_default_region(self):
        self.assertEqual(tc.base_url({}), "https://tds.eu.cloud.talend.com")


class TestNeedToken(unittest.TestCase):
    def test_missing_token_exits(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit):
                tc.need_token({})

    def test_token_from_cfg(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(tc.need_token({"tds.token": "abc"}), "abc")


class TestBuildUrl(unittest.TestCase):
    def setUp(self):
        self.c = tc.TdsClient(cfg={"tds.base_url": "https://tds.eu.cloud.talend.com",
                                   "tds.token": "t"})

    def test_path_join(self):
        self.assertEqual(self.c.build_url("/a/b"),
                         "https://tds.eu.cloud.talend.com/a/b")

    def test_path_without_leading_slash(self):
        self.assertEqual(self.c.build_url("a/b"),
                         "https://tds.eu.cloud.talend.com/a/b")

    def test_params_drop_none(self):
        url = self.c.build_url("/x", {"query": "a=1", "skip": None})
        self.assertEqual(url, "https://tds.eu.cloud.talend.com/x?query=a%3D1")


class TestDryRun(unittest.TestCase):
    def setUp(self):
        self.c = tc.TdsClient(cfg={"tds.base_url": "https://x", "tds.token": "t"},
                              dry_run=True)

    def test_mutating_returns_sentinel_without_network(self):
        # urlopen would raise if called; dry-run must not call it.
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("network called in dry-run")):
            out = self.c.request("POST", "/p", body={"a": 1})
        self.assertTrue(out["_dry_run"])
        self.assertEqual(out["method"], "POST")
        self.assertEqual(out["body"], {"a": 1})


class TestExtractError(unittest.TestCase):
    def test_errors_array(self):
        msg, code = tc._extract_error(
            '{"errors":[{"code":"error.campaign.name.patternNotMatched",'
            '"message":"The campaign name does not match the pattern."}]}')
        self.assertEqual(code, "error.campaign.name.patternNotMatched")
        self.assertIn("does not match", msg)

    def test_code_message_context(self):
        msg, code = tc._extract_error(
            '{"code":"SCHEMA_NAME_ALREADY_EXISTS","message":"SCHEMA_NAME_ALREADY_EXISTS",'
            '"context":{"name":"demo_product"}}')
        self.assertEqual(code, "SCHEMA_NAME_ALREADY_EXISTS")

    def test_spring_not_found(self):
        msg, code = tc._extract_error(
            '{"timestamp":"x","status":404,"error":"Not Found","path":"/api/v1/tasks"}')
        self.assertEqual(msg, "Not Found")

    def test_non_json(self):
        msg, code = tc._extract_error("<html>boom</html>")
        self.assertIsNone(code)
        self.assertIn("boom", msg)


class TestAsList(unittest.TestCase):
    def test_bare_array(self):
        self.assertEqual(tc.as_list([1, 2]), [1, 2])

    def test_items_wrapper(self):
        self.assertEqual(tc.as_list({"items": [1]}), [1])

    def test_none(self):
        self.assertEqual(tc.as_list(None), [])

    def test_single_object_wrapped(self):
        self.assertEqual(tc.as_list({"id": "x"}), [{"id": "x"}])


if __name__ == "__main__":
    unittest.main()
