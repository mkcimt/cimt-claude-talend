"""Read-only guarantee tests for the TMC client. These lock the safety property
into CI: the client must NEVER be able to issue a mutating request, even when
handed a write-capable token. All offline — no network."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import tmc_client as tc  # noqa: E402


def _client():
    # Constructed with an explicit base + token so nothing reads config or network.
    return tc.TmcClient(cfg={"tmc.region": "eu"}, token="dummy",
                        base="https://api.eu.cloud.talend.com")


class TestReadOnlyGuard(unittest.TestCase):
    def test_non_get_methods_are_refused(self):
        c = _client()
        for verb in ("POST", "PUT", "PATCH", "DELETE", "post", "Delete", "OPTIONS", ""):
            with self.assertRaises(tc.TmcReadOnlyViolation):
                c._request(verb, "/orchestration/environments")

    def test_off_allowlist_path_is_refused(self):
        c = _client()
        for bad in ("/some/write/endpoint", "/orchestrationX/y", "/v1/tasks/run"):
            with self.assertRaises(tc.TmcReadOnlyViolation):
                c.get(bad)

    def test_allowed_read_prefixes_pass_the_guard(self):
        # _ensure_allowed must NOT raise for the read products (it only checks the path).
        for ok in ("/orchestration/environments", "/processing/engines",
                   "/observability/metrics", "/execution-history/search"):
            tc.TmcClient._ensure_allowed(ok)  # no exception == pass

    def test_only_verb_method_is_get(self):
        c = _client()
        self.assertTrue(hasattr(c, "get"))
        for forbidden in ("post", "put", "patch", "delete", "create", "update", "run", "trigger"):
            self.assertFalse(hasattr(c, forbidden), f"client must not expose .{forbidden}()")

    def test_source_has_no_mutating_urllib_request(self):
        src = Path(tc.__file__).read_text()
        verbs = re.findall(r'\.Request\([^)]*?method\s*=\s*["\'](\w+)["\']', src)
        self.assertTrue(verbs)
        self.assertEqual(set(verbs), {"GET"}, f"non-GET urllib Request found: {verbs}")


class TestUrlAndConfig(unittest.TestCase):
    def test_build_url_and_param_encoding(self):
        c = _client()
        self.assertEqual(c.build_url("/orchestration/environments"),
                         "https://api.eu.cloud.talend.com/orchestration/environments")
        self.assertEqual(c.build_url("orchestration/tasks", {"limit": 50, "skip": None}),
                         "https://api.eu.cloud.talend.com/orchestration/tasks?limit=50")

    def test_base_url_from_region_and_override(self):
        self.assertEqual(tc.base_url({"tmc.region": "us"}), "https://api.us.cloud.talend.com")
        self.assertEqual(tc.base_url({"tmc.base_url": "https://x/"}), "https://x")
        self.assertEqual(tc.base_url({}), "https://api.eu.cloud.talend.com")  # default region

    def test_audit_records_nothing_until_a_call(self):
        self.assertEqual(_client().calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
