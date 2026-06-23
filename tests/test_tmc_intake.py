"""Tests for the read-only TMC enrichment + correlation, using a fake client with
canned responses (no network). Also asserts the enrichment only ever reads
(GET) — it never invokes a mutating verb."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_intake as pi  # noqa: E402
import tmc_intake  # noqa: E402
from test_project_intake import build_fixture  # noqa: E402

# Canned TMC responses keyed by path. A single task named after a fixture job,
# so we can assert deployed / reachable-via-parent / orphaned classification.
_CANNED = {
    "/orchestration/environments": [
        {"id": "e1", "name": "prd", "default": False, "maxCloudContainers": 2},
        {"id": "e2", "name": "dev", "default": True, "maxCloudContainers": 1},
    ],
    "/orchestration/workspaces": [
        {"id": "w1", "name": "ws", "type": "custom", "owner": "o",
         "environment": {"id": "e1", "name": "prd"}},
    ],
    "/processing/engines": {"count": 1, "enginesInfo": [
        {"id": "g1", "engineId": "eng1", "packageVersion": "2026-04", "services": [1, 2]},
    ]},
    "/orchestration/executables/tasks": {"items": [
        {"executable": "t1", "name": "j_orders_top", "artifactId": "a1",
         "runtime": {"type": "REMOTE_ENGINE_CLUSTER", "id": "c1"},
         "workspace": {"id": "w1", "environment": {"id": "e1"}},
         "taskPauseDetails": {"pause": False}},
    ], "total": 1, "limit": 100, "offset": 0},
    "/orchestration/executables/plans": {"items": [
        {"executable": "p1", "name": "plan1", "workspace": {"id": "w1"},
         "chart": {"flows": [{"id": "f1", "workspaceId": "w1"}], "nextStep": None}},
    ], "total": 1, "limit": 100, "offset": 0},
}


class FakeTmcClient:
    """Records every access and only exposes read verbs (get / get_all)."""

    def __init__(self):
        self.cfg = {"tmc.region": "eu"}
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(("GET", path))
        return _CANNED.get(path)

    def get_all(self, path, params=None, *, items_key=None, page_size=100, max_pages=1000):
        self.calls.append(("GET", path))
        data = _CANNED.get(path)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get(items_key or "items", [])
        return []


class TestTmcEnrichment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        build_fixture(root)
        cls.doc = pi.analyze(root)
        cls.fake = FakeTmcClient()
        tmc_intake.enrich(cls.doc, client=cls.fake, generated_at="2026-06-23T00:00:00Z")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _art(self, name):
        return next(a for a in self.doc["artifacts"] if a["name"] == name)

    def test_blocks_populated_with_tmc_provenance(self):
        self.assertTrue(self.doc["tmc"]["enriched"])
        self.assertEqual(self.doc["tmc"]["region"], "eu")
        self.assertEqual(len(self.doc["environments"]), 2)
        self.assertTrue(all(e["provenance"] == "tmc" for e in self.doc["environments"]))
        self.assertEqual(len(self.doc["infrastructure"]["engines"]), 1)
        self.assertEqual(len(self.doc["infrastructure"]["workspaces"]), 1)
        self.assertEqual(len(self.doc["tmc"]["tasks"]), 1)
        self.assertEqual(len(self.doc["tmc"]["plans"]), 1)

    def test_deployed_artifact_gets_tmc_task(self):
        top = self._art("j_orders_top")
        self.assertIsNotNone(top["tmc_task"])
        self.assertEqual(top["tmc_task"]["provenance"], "tmc")
        self.assertEqual(top["tmc_task"]["task_ids"], ["t1"])
        # task t1's workspace is in environment e1 == 'prd' -> per-env presence + prod flag.
        self.assertEqual(top["tmc_task"]["deployed_in_environments"], ["prd"])
        self.assertTrue(top["tmc_task"]["in_prod"])

    def test_summary_per_environment(self):
        s = self.doc["tmc"]["summary"]
        self.assertEqual(s["deployed_in_prod"], 1)
        self.assertEqual(s["deployment_by_environment"], {"prd": 1})

    def test_correlation_classification(self):
        s = self.doc["tmc"]["summary"]
        # fixture deployable jobs/routes: j_orders_top, j_orders_work, j_uses_joblet,
        # j_broken (jobs) + r_dispatch (route) = 5.
        self.assertEqual(s["deployable_total"], 5)
        self.assertEqual(s["deployed"], 1)               # j_orders_top has a task
        self.assertEqual(s["reachable_via_parent"], 1)   # j_orders_work, called by top
        self.assertEqual(len(s["orphaned_candidates"]), 3)
        self.assertIn("j_uses_joblet", s["orphaned_candidates"])

    def test_enrichment_is_read_only(self):
        # Every access through the client was a GET; no mutating verb ever used.
        self.assertTrue(self.fake.calls)
        self.assertEqual({m for m, _ in self.fake.calls}, {"GET"})

    def test_environments_have_names(self):
        names = {e["name"] for e in self.doc["environments"]}
        self.assertEqual(names, {"prd", "dev"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
