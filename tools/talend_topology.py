"""
talend_topology.py — build the project call graph and propose *logical interfaces*
(clusters of artifacts) from structural signals.

Because the projects we analyse often have no naming conventions, grouping
artifacts into "an interface" is an inference, never a fact. We therefore:

- build a directed **call graph** from `tRunJob` / `cTalendJob` edges, and
- build a weighted **cluster graph** combining: call edges (5), shared context
  groups (3), shared repository connections (2), shared domain joblets (2),
  same folder subtree (1).

Strong cores come from call edges; weakly-connected artifacts attach to the
nearest core by vote, and anything that could belong to two cores is flagged
`ambiguous` rather than force-merged. Every cluster is emitted with
`status="proposed"` — a human confirms or renames it in the manual phase.
Cluster weights are tunable defaults; a shared staging DB or an org-wide utility
joblet can over-merge, which is exactly why ambiguity is surfaced, not hidden.

Pure graph logic on stdlib. Also computes cross-file `runjob_depth`, fed back
into the complexity metric.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Cluster-edge weights (tunable defaults).
W_CALL = 5
W_CONTEXT = 3
W_REPO_CONN = 2
W_JOBLET = 2
W_FOLDER = 1

# A signal (context group / repo connection / joblet / folder) shared by MORE than
# this many artifacts is a project-wide UTILITY, not an interface marker — it must
# not glue unrelated interfaces together. Tunable.
MAX_SHARED_FANOUT = 8
# A job called via tRunJob by MORE than this many distinct callers is a shared
# helper/utility — the call edge is kept for topology/depth, but its callers are
# NOT merged into one interface core through it. Tunable.
UTILITY_CALL_FANOUT = 5


@dataclass
class ArtifactNode:
    """The slice of an artifact the topology cares about."""

    id: str
    name: str
    type: str = "job"
    rel_dir: str = ""
    call_targets: list[str] = field(default_factory=list)   # job names called via tRunJob/cTalendJob
    context_groups: list[str] = field(default_factory=list)
    repo_connections: list[str] = field(default_factory=list)
    joblets: list[str] = field(default_factory=list)


def _interface_id(member_ids: Iterable[str]) -> str:
    """Deterministic id from sorted members, so manual renames survive re-analysis."""
    h = hashlib.sha1("|".join(sorted(member_ids)).encode("utf-8")).hexdigest()[:8]
    return f"if-{h}"


def build_call_graph(nodes: list[ArtifactNode]) -> dict:
    """Resolve call_targets (by name) to artifact ids. Returns adjacency + unresolved."""
    name_index: dict[str, str] = {}
    for n in nodes:
        # Last writer wins on duplicate names; both name and id are indexed.
        name_index[n.name] = n.id
        name_index[n.id] = n.id
    adj: dict[str, set[str]] = {n.id: set() for n in nodes}
    rev: dict[str, set[str]] = {n.id: set() for n in nodes}
    unresolved: list[tuple[str, str]] = []
    for n in nodes:
        for tgt in n.call_targets:
            tid = name_index.get(tgt)
            if tid and tid != n.id:
                adj[n.id].add(tid)
                rev[tid].add(n.id)
            elif not tid:
                unresolved.append((n.id, tgt))
    return {"adj": adj, "rev": rev, "name_index": name_index, "unresolved": unresolved}


def longest_downstream_depths(call_graph: dict) -> dict[str, int]:
    """Longest downstream call chain (in edges) from each node, cycle-guarded."""
    adj = call_graph["adj"]
    memo: dict[str, int] = {}

    def dfs(node: str, stack: set[str]) -> int:
        if node in memo:
            return memo[node]
        best = 0
        for nxt in adj.get(node, ()):
            if nxt in stack:        # cycle — stop descending this branch
                continue
            best = max(best, 1 + dfs(nxt, stack | {nxt}))
        memo[node] = best
        return best

    return {node: dfs(node, {node}) for node in adj}


class _UnionFind:
    def __init__(self, items: Iterable[str]):
        self.parent = {i: i for i in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_cluster_graph(nodes: list[ArtifactNode], call_graph: dict) -> dict[tuple[str, str], int]:
    """Weighted undirected edges between artifacts from all clustering signals."""
    edges: dict[tuple[str, str], int] = {}

    def add(a: str, b: str, w: int) -> None:
        if a == b:
            return
        key = (a, b) if a < b else (b, a)
        edges[key] = edges.get(key, 0) + w

    # Call edges.
    for src, dsts in call_graph["adj"].items():
        for dst in dsts:
            add(src, dst, W_CALL)

    # Shared context groups / repo connections / joblets — but a value shared by
    # more than MAX_SHARED_FANOUT artifacts is a utility, not an interface marker.
    def shared(attr: str, weight: int) -> None:
        index: dict[str, list[str]] = {}
        for n in nodes:
            for val in getattr(n, attr):
                index.setdefault(val, []).append(n.id)
        for ids in index.values():
            if len(ids) > MAX_SHARED_FANOUT:
                continue  # project-wide utility — do not glue interfaces together
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    add(ids[i], ids[j], weight)

    shared("context_groups", W_CONTEXT)
    shared("repo_connections", W_REPO_CONN)
    shared("joblets", W_JOBLET)

    # Same immediate folder subtree (one level under the top folder), same cap.
    folder_index: dict[str, list[str]] = {}
    for n in nodes:
        parts = n.rel_dir.split("/")
        subtree = "/".join(parts[:2]) if len(parts) >= 2 else n.rel_dir
        if subtree:
            folder_index.setdefault(subtree, []).append(n.id)
    for ids in folder_index.values():
        if len(ids) > MAX_SHARED_FANOUT:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                add(ids[i], ids[j], W_FOLDER)

    return edges


def propose_interfaces(nodes: list[ArtifactNode], call_graph: dict,
                       cluster_graph: dict[tuple[str, str], int]) -> list[dict]:
    """Cores from call edges; attach weak nodes by strongest vote; flag ambiguity."""
    ids = [n.id for n in nodes]
    by_id = {n.id: n for n in nodes}
    adj = call_graph["adj"]
    rev = call_graph["rev"]

    # 1) Strong cores = connected components over CALL edges only — but NOT through
    #    a shared utility/helper job (one called by many distinct callers), which
    #    would otherwise merge every interface that reuses it into one blob.
    utility = {n for n in rev if len(rev.get(n, ())) > UTILITY_CALL_FANOUT}
    uf = _UnionFind(ids)
    for (a, b), w in cluster_graph.items():
        callee = b if b in adj.get(a, ()) else (a if a in adj.get(b, ()) else None)
        if callee is None:
            continue                      # not a call edge
        if callee in utility:
            continue                      # shared helper — keep the edge, don't merge cores
        uf.union(a, b)
    cores: dict[str, set[str]] = {}
    for i in ids:
        cores.setdefault(uf.find(i), set()).add(i)

    # 2) Attach a node that is its own core (no call edge) to the best neighbouring core.
    core_of = {i: uf.find(i) for i in ids}
    # Per-node best non-call attachment(s) — store the neighbour NODE id, not its
    # core root, so we can resolve the (possibly already re-homed) core LIVE at apply
    # time. Storing the snapshot root would orphan a singleton whose neighbour moved.
    weak_attach: dict[str, list[tuple[int, str]]] = {i: [] for i in ids}
    for (a, b), w in cluster_graph.items():
        weak_attach[a].append((w, b))
        weak_attach[b].append((w, a))

    ambiguous: set[str] = set()
    for i in ids:
        # Only singletons (their own core, size 1) are eligible to be re-homed.
        if len(cores[core_of[i]]) != 1:
            continue
        cands = sorted(((w, core_of[nbr]) for (w, nbr) in weak_attach[i]
                        if core_of[nbr] != core_of[i]), reverse=True)
        if not cands:
            continue
        top_w = cands[0][0]
        top_cores = {c for w, c in cands if w == top_w}
        # Re-home into the single best core (resolved live).
        target = cands[0][1]
        cores[core_of[i]].discard(i)
        cores.setdefault(target, set()).add(i)
        core_of[i] = target
        if len(top_cores) > 1:
            ambiguous.add(i)

    cores = {root: members for root, members in cores.items() if members}

    interfaces: list[dict] = []
    for members in cores.values():
        members_sorted = sorted(members)
        # Entry points = members with no caller *inside* this cluster.
        entries = [m for m in members_sorted if not (rev.get(m, set()) & members)]
        has_call = any((m in adj and adj[m] & members) for m in members_sorted)
        if len(members_sorted) == 1:
            confidence = "low"
        elif has_call:
            confidence = "high"
        else:
            confidence = "medium"
        signals = {
            "runjob_edges": sum(1 for m in members_sorted for d in adj.get(m, ()) if d in members),
            "shared_context_groups": sorted({g for m in members_sorted for g in by_id[m].context_groups}),
            "shared_repo_connections": sorted({c for m in members_sorted for c in by_id[m].repo_connections}),
            "shared_domain_joblets": sorted({j for m in members_sorted for j in by_id[m].joblets}),
            "same_folder_subtree": len({by_id[m].rel_dir.split("/")[0] for m in members_sorted}) == 1,
        }
        interfaces.append({
            "interface_id": _interface_id(members_sorted),
            "label": "(proposed)",
            "status": "proposed",
            "confidence": confidence,
            "entry_points": entries or members_sorted[:1],
            "member_artifacts": members_sorted,
            "cluster_signals": signals,
            "ambiguous_members": sorted(ambiguous & members),
            "systems_touched": [],   # filled by the orchestrator
            "tmc_plan_ref": None,
            "provenance": "static",
        })
    interfaces.sort(key=lambda iface: (-len(iface["member_artifacts"]), iface["interface_id"]))
    return interfaces


if __name__ == "__main__":
    # A -> B -> C call chain (one interface) + D,E sharing a context group (another)
    # + F isolated.
    nodes = [
        ArtifactNode("a1", "top", call_targets=["disp"], rel_dir="process/iA"),
        ArtifactNode("a2", "disp", call_targets=["work"], rel_dir="process/iA"),
        ArtifactNode("a3", "work", rel_dir="process/iA"),
        ArtifactNode("a4", "d", context_groups=["ctxX"], rel_dir="process/iB"),
        ArtifactNode("a5", "e", context_groups=["ctxX"], rel_dir="process/iB"),
        ArtifactNode("a6", "lonely", rel_dir="process/iC"),
    ]
    cg = build_call_graph(nodes)
    assert cg["adj"]["a1"] == {"a2"}
    assert cg["adj"]["a2"] == {"a3"}

    depths = longest_downstream_depths(cg)
    assert depths["a1"] == 2 and depths["a2"] == 1 and depths["a3"] == 0

    clg = build_cluster_graph(nodes, cg)
    ifaces = propose_interfaces(nodes, cg, clg)

    # Find the call-chain interface.
    chain = next(i for i in ifaces if set(i["member_artifacts"]) >= {"a1", "a2", "a3"})
    assert chain["confidence"] == "high"
    assert chain["entry_points"] == ["a1"]

    ctx_iface = next(i for i in ifaces if set(i["member_artifacts"]) == {"a4", "a5"})
    assert ctx_iface["confidence"] == "medium"
    assert ctx_iface["cluster_signals"]["shared_context_groups"] == ["ctxX"]

    lonely = next(i for i in ifaces if i["member_artifacts"] == ["a6"])
    assert lonely["confidence"] == "low"

    # Deterministic ids across runs.
    assert _interface_id(["b", "a"]) == _interface_id(["a", "b"])

    # Re-homing must follow a neighbour into its LIVE core, never a stale (emptied)
    # root. s1 re-homes into the c1/c2 call core (tie weight 5); s2's only link is to
    # s1, so s2 must follow s1 there — not get orphaned in s1's vacated root.
    rehome = [
        ArtifactNode("c1", "c1", call_targets=["c2"]),
        ArtifactNode("c2", "c2", context_groups=["g"], repo_connections=["r"]),
        ArtifactNode("s1", "s1", context_groups=["g", "h"], repo_connections=["r"]),
        ArtifactNode("s2", "s2", context_groups=["h"]),
    ]
    rg = build_call_graph(rehome)
    ri = propose_interfaces(rehome, rg, build_cluster_graph(rehome, rg))
    s2_iface = next(i for i in ri if "s2" in i["member_artifacts"])
    assert {"c1", "c2", "s1", "s2"} <= set(s2_iface["member_artifacts"]), \
        [i["member_artifacts"] for i in ri]

    # Cycle guard: A->B->A must terminate with finite depths (longest path in a
    # cyclic graph is ill-defined; the only contract is "no hang / no overflow").
    cyc = [ArtifactNode("x", "x", call_targets=["y"]), ArtifactNode("y", "y", call_targets=["x"])]
    cgc = build_call_graph(cyc)
    d = longest_downstream_depths(cgc)
    assert isinstance(d["x"], int) and d["x"] >= 0
    assert isinstance(d["y"], int) and d["y"] >= 0

    print("talend_topology.py self-test passed")
