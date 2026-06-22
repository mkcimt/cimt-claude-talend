"""Offline unit tests for talend_topology.py — call-graph construction and
logical-interface proposal from structural signals. Pure graph logic; fixtures
are synthetic ArtifactNode lists (customer-agnostic ids/names).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import talend_topology as topo  # noqa: E402
from talend_topology import ArtifactNode  # noqa: E402


class TestBuildCallGraph(unittest.TestCase):
    def test_resolves_targets_by_name_to_ids(self):
        nodes = [
            ArtifactNode("a1", "top", call_targets=["disp"]),
            ArtifactNode("a2", "disp", call_targets=["work"]),
            ArtifactNode("a3", "work"),
        ]
        cg = topo.build_call_graph(nodes)
        self.assertEqual(cg["adj"]["a1"], {"a2"})
        self.assertEqual(cg["adj"]["a2"], {"a3"})
        self.assertEqual(cg["adj"]["a3"], set())
        # Reverse edges recorded too.
        self.assertEqual(cg["rev"]["a2"], {"a1"})
        self.assertEqual(cg["unresolved"], [])

    def test_records_unresolved_targets(self):
        nodes = [ArtifactNode("a1", "top", call_targets=["ghost"])]
        cg = topo.build_call_graph(nodes)
        self.assertEqual(cg["unresolved"], [("a1", "ghost")])
        self.assertEqual(cg["adj"]["a1"], set())

    def test_resolves_target_by_id(self):
        # call_target referencing the id directly resolves too.
        nodes = [ArtifactNode("a1", "top", call_targets=["a2"]),
                 ArtifactNode("a2", "other")]
        cg = topo.build_call_graph(nodes)
        self.assertEqual(cg["adj"]["a1"], {"a2"})

    def test_self_call_not_an_edge(self):
        nodes = [ArtifactNode("a1", "self", call_targets=["self"])]
        cg = topo.build_call_graph(nodes)
        self.assertEqual(cg["adj"]["a1"], set())
        self.assertEqual(cg["unresolved"], [])


class TestLongestDownstreamDepths(unittest.TestCase):
    def test_correct_on_dag(self):
        nodes = [
            ArtifactNode("a", "a", call_targets=["b"]),
            ArtifactNode("b", "b", call_targets=["c"]),
            ArtifactNode("c", "c"),
        ]
        depths = topo.longest_downstream_depths(topo.build_call_graph(nodes))
        self.assertEqual(depths["a"], 2)
        self.assertEqual(depths["b"], 1)
        self.assertEqual(depths["c"], 0)

    def test_terminates_on_cycle_with_finite_ints(self):
        nodes = [
            ArtifactNode("a", "a", call_targets=["b"]),
            ArtifactNode("b", "b", call_targets=["a"]),
        ]
        depths = topo.longest_downstream_depths(topo.build_call_graph(nodes))
        self.assertIsInstance(depths["a"], int)
        self.assertIsInstance(depths["b"], int)
        self.assertGreaterEqual(depths["a"], 0)
        self.assertGreaterEqual(depths["b"], 0)

    def test_diamond_takes_longest_branch(self):
        # a->b->d and a->c ; longest from a is 2.
        nodes = [
            ArtifactNode("a", "a", call_targets=["b", "c"]),
            ArtifactNode("b", "b", call_targets=["d"]),
            ArtifactNode("c", "c"),
            ArtifactNode("d", "d"),
        ]
        depths = topo.longest_downstream_depths(topo.build_call_graph(nodes))
        self.assertEqual(depths["a"], 2)


class TestBuildClusterGraph(unittest.TestCase):
    def test_call_edge_weighted(self):
        nodes = [ArtifactNode("a", "a", call_targets=["b"]),
                 ArtifactNode("b", "b")]
        cg = topo.build_call_graph(nodes)
        clg = topo.build_cluster_graph(nodes, cg)
        self.assertEqual(clg[("a", "b")], topo.W_CALL)

    def test_shared_context_group_weighted(self):
        nodes = [ArtifactNode("a", "a", context_groups=["ctxX"]),
                 ArtifactNode("b", "b", context_groups=["ctxX"])]
        clg = topo.build_cluster_graph(nodes, topo.build_call_graph(nodes))
        self.assertEqual(clg[("a", "b")], topo.W_CONTEXT)

    def test_weights_accumulate(self):
        # A call edge AND a shared context group between the same pair add up.
        nodes = [ArtifactNode("a", "a", call_targets=["b"], context_groups=["g"]),
                 ArtifactNode("b", "b", context_groups=["g"])]
        clg = topo.build_cluster_graph(nodes, topo.build_call_graph(nodes))
        self.assertEqual(clg[("a", "b")], topo.W_CALL + topo.W_CONTEXT)

    def test_shared_folder_subtree_weighted(self):
        nodes = [ArtifactNode("a", "a", rel_dir="process/iA"),
                 ArtifactNode("b", "b", rel_dir="process/iA")]
        clg = topo.build_cluster_graph(nodes, topo.build_call_graph(nodes))
        self.assertEqual(clg[("a", "b")], topo.W_FOLDER)


class TestProposeInterfaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A->B->C call chain (high), D&E share a context group (medium),
        # F isolated (low). Distinct folders so folder weight doesn't merge them.
        cls.nodes = [
            ArtifactNode("a1", "top", call_targets=["disp"], rel_dir="process/iA"),
            ArtifactNode("a2", "disp", call_targets=["work"], rel_dir="process/iA"),
            ArtifactNode("a3", "work", rel_dir="process/iA"),
            ArtifactNode("a4", "d", context_groups=["ctxX"], rel_dir="process/iB"),
            ArtifactNode("a5", "e", context_groups=["ctxX"], rel_dir="process/iB"),
            ArtifactNode("a6", "lonely", rel_dir="process/iC"),
        ]
        cls.cg = topo.build_call_graph(cls.nodes)
        cls.clg = topo.build_cluster_graph(cls.nodes, cls.cg)
        cls.ifaces = topo.propose_interfaces(cls.nodes, cls.cg, cls.clg)

    def _iface_with(self, *members):
        want = set(members)
        return next(i for i in self.ifaces
                    if set(i["member_artifacts"]) >= want)

    def test_high_confidence_call_chain(self):
        chain = self._iface_with("a1", "a2", "a3")
        self.assertEqual(set(chain["member_artifacts"]), {"a1", "a2", "a3"})
        self.assertEqual(chain["confidence"], "high")
        # Entry point = the in-degree-0 node of the chain.
        self.assertEqual(chain["entry_points"], ["a1"])
        self.assertEqual(chain["status"], "proposed")

    def test_medium_confidence_shared_context(self):
        ctx = next(i for i in self.ifaces
                   if set(i["member_artifacts"]) == {"a4", "a5"})
        self.assertEqual(ctx["confidence"], "medium")
        self.assertEqual(ctx["cluster_signals"]["shared_context_groups"], ["ctxX"])

    def test_low_confidence_singleton(self):
        lonely = next(i for i in self.ifaces if i["member_artifacts"] == ["a6"])
        self.assertEqual(lonely["confidence"], "low")
        # A singleton is its own entry point.
        self.assertEqual(lonely["entry_points"], ["a6"])

    def test_every_interface_proposed_and_static(self):
        for i in self.ifaces:
            self.assertEqual(i["status"], "proposed")
            self.assertEqual(i["provenance"], "static")
            self.assertTrue(i["interface_id"].startswith("if-"))


class TestDeterministicInterfaceId(unittest.TestCase):
    def test_order_independent(self):
        self.assertEqual(topo._interface_id(["b", "a"]),
                         topo._interface_id(["a", "b"]))

    def test_distinct_members_distinct_id(self):
        self.assertNotEqual(topo._interface_id(["a", "b"]),
                            topo._interface_id(["a", "c"]))

    def test_id_format(self):
        self.assertTrue(topo._interface_id(["a"]).startswith("if-"))


class TestAmbiguousFlagging(unittest.TestCase):
    def test_singleton_pulled_equally_toward_two_cores_is_ambiguous(self):
        # Two independent call-chain cores: (c1->c2) and (d1->d2). A singleton S
        # shares one context group with core1 and one with core2 at EQUAL weight,
        # and has no call edge of its own -> it must be flagged ambiguous.
        nodes = [
            ArtifactNode("c1", "c1", call_targets=["c2"], rel_dir="x/c"),
            ArtifactNode("c2", "c2", context_groups=["gC"], rel_dir="x/c"),
            ArtifactNode("d1", "d1", call_targets=["d2"], rel_dir="x/d"),
            ArtifactNode("d2", "d2", context_groups=["gD"], rel_dir="x/d"),
            ArtifactNode("s", "s", context_groups=["gC", "gD"], rel_dir="x/s"),
        ]
        cg = topo.build_call_graph(nodes)
        clg = topo.build_cluster_graph(nodes, cg)
        ifaces = topo.propose_interfaces(nodes, cg, clg)
        # Find the interface that ended up containing the singleton s.
        owning = next(i for i in ifaces if "s" in i["member_artifacts"])
        self.assertIn("s", owning["ambiguous_members"])


if __name__ == "__main__":
    unittest.main()
