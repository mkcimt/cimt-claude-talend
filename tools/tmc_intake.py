#!/usr/bin/env python3
"""
tmc_intake.py — phase-3 TMC enrichment for project-intake. READ-ONLY.

Reads TMC state through the strictly read-only `tmc_client` and fills the
canonical document's reserved `environments`, `infrastructure` and `tmc{}`
blocks, then correlates deployed TMC tasks back to the static `artifacts[]`
(which jobs are actually deployed, and where) and plans to `interfaces[]`.

Every fact added here carries `provenance="tmc"`. This module never mutates TMC:
all access goes through `tmc_client`, which can only issue GET requests.

Field shapes are mapped from the live TMC Public API (orchestration/processing):
  environments   GET /orchestration/environments          -> {id,name,default,maxCloudContainers}
  workspaces     GET /orchestration/workspaces            -> {id,name,type,owner,environment{...}}
  engines        GET /processing/engines                  -> {count, enginesInfo:[{engineId,id,packageVersion,...}]}
  tasks          GET /orchestration/executables/tasks     -> paginated {items:[{executable,name,artifactId,runtime{type,id,runProfileId},workspace{...},taskPauseDetails}]}
  plans          GET /orchestration/executables/plans     -> paginated {items:[{executable,name,workspace{...},chart{flows,nextStep}}]}
  executions     GET /orchestration/executables/tasks/{id}/executions  (opt-in stats)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmc_client as tc  # noqa: E402

UNRESOLVED = "(unresolved)"

# Artifact types that are deployable as a standalone TMC task. Joblets/routelets/
# routines are NOT — they run inside a parent, so they never have their own task.
DEPLOYABLE_TYPES = {"job", "route", "service", "spark_job", "spark_streaming_job", "mr_job"}

# Terminal execution statuses (best-effort; refine against more live data).
_SUCCESS_STATES = {"EXECUTION_SUCCESS", "SUCCESS", "DEPLOY_SUCCESS"}
_FAILURE_STATES = {"EXECUTION_FAILED", "FAILED", "EXECUTION_ROLLBACK", "DEPLOY_FAILED", "EXECUTION_ERROR"}


def _ws_env_id(ws: dict) -> str:
    env = ws.get("environment")
    if isinstance(env, dict):
        return env.get("id", "")
    return env or ""


def fetch_environments(client: tc.TmcClient) -> list[dict]:
    out = []
    for e in client.get("/orchestration/environments") or []:
        out.append({
            "id": e.get("id", ""), "name": e.get("name", ""),
            "description": e.get("description", ""),
            "max_cloud_containers": e.get("maxCloudContainers"),
            "is_default": bool(e.get("default")), "provenance": "tmc",
        })
    return out


def fetch_workspaces(client: tc.TmcClient) -> list[dict]:
    out = []
    for w in client.get("/orchestration/workspaces") or []:
        out.append({
            "id": w.get("id", ""), "name": w.get("name", ""),
            "type": w.get("type", ""), "environment_id": _ws_env_id(w),
            "owner": (w.get("owner") or ""), "provenance": "tmc",
        })
    return out


def fetch_engines(client: tc.TmcClient) -> list[dict]:
    data = client.get("/processing/engines") or {}
    out = []
    for e in (data.get("enginesInfo") or []):
        out.append({
            "id": e.get("id", ""), "engine_id": e.get("engineId", ""),
            "package_version": e.get("packageVersion", ""),
            "n_services": len(e.get("services") or []),
            "retrieval_date": e.get("retrievalDate", ""),
            "provenance": "tmc",
        })
    return out


def fetch_tasks(client: tc.TmcClient) -> list[dict]:
    out = []
    for t in client.get_all("/orchestration/executables/tasks", items_key="items"):
        runtime = t.get("runtime") or {}
        ws = t.get("workspace") or {}
        pause = t.get("taskPauseDetails") or {}
        out.append({
            "id": t.get("executable", ""), "name": t.get("name", ""),
            "artifact_tmc_id": t.get("artifactId", ""),
            "workspace_id": ws.get("id", "") if isinstance(ws, dict) else ws,
            "environment_id": _ws_env_id(ws) if isinstance(ws, dict) else "",
            "runtime_type": runtime.get("type", ""),
            "runtime_id": runtime.get("id", ""),
            "run_profile_id": runtime.get("runProfileId"),
            "paused": bool(pause.get("pause")),
            "tags": t.get("tags") or [],
            "provenance": "tmc",
        })
    return out


def fetch_plans(client: tc.TmcClient) -> list[dict]:
    out = []
    for p in client.get_all("/orchestration/executables/plans", items_key="items"):
        ws = p.get("workspace") or {}
        chart = p.get("chart") or {}
        flows = chart.get("flows") or []
        out.append({
            "id": p.get("executable", ""), "name": p.get("name", ""),
            "description": p.get("description", ""),
            "workspace_id": ws.get("id", "") if isinstance(ws, dict) else ws,
            "environment_id": _ws_env_id(ws) if isinstance(ws, dict) else "",
            # chart.flows are thin ({id, workspaceId}); full step→task membership
            # needs a deeper plan-detail probe (see BACKLOG). Capture what's here.
            "n_flows": len(flows),
            "flow_ids": [f.get("id", "") for f in flows if isinstance(f, dict)],
            "provenance": "tmc",
        })
    return out


def aggregate_task_stats(client: tc.TmcClient, task_id: str,
                         window_days: int = 90, max_records: int = 500) -> Optional[dict]:
    """Best-effort per-task execution stats from the executions endpoint. Read-only.

    Returns counts + cadence; durations are omitted until a finish/duration field
    is confirmed against completed executions (see BACKLOG).
    """
    try:
        items = client.get_all(f"/orchestration/executables/tasks/{task_id}/executions",
                               items_key="items", page_size=100,
                               max_pages=max(1, max_records // 100))
    except tc.TmcError:
        return None
    if not items:
        return {"task_id": task_id, "run_count": 0, "provenance": "tmc"}
    succ = sum(1 for e in items if str(e.get("status", "")).upper() in _SUCCESS_STATES)
    fail = sum(1 for e in items if str(e.get("status", "")).upper() in _FAILURE_STATES)
    triggers = [e.get("triggerTimestamp") or e.get("startTimestamp") for e in items]
    triggers = sorted(t for t in triggers if t)
    types = {}
    for e in items:
        k = e.get("executionType", "")
        types[k] = types.get(k, 0) + 1
    return {
        "task_id": task_id, "run_count": len(items),
        "success_count": succ, "failure_count": fail,
        "success_rate": round(succ / len(items), 3) if items else None,
        "last_run_time": triggers[-1] if triggers else None,
        "first_seen_time": triggers[0] if triggers else None,
        "dominant_trigger_type": max(types, key=types.get) if types else "",
        "provenance": "tmc",
    }


_PROD_NAMES = {"prd", "prod", "production"}


def correlate(doc: dict, tasks: list[dict], plans: list[dict],
              env_map: Optional[dict] = None) -> dict:
    """Link TMC tasks to static artifacts (by name), capturing per-environment
    deployment presence. A job can have tasks in several environments; we record
    the set and flag prod presence (prod is the authoritative 'what runs' view —
    non-prod is often stale).
    """
    env_map = env_map or {}
    by_name: dict[str, dict] = {}
    by_id: dict[str, dict] = {}
    for a in doc.get("artifacts", []):
        by_name.setdefault(a["name"], a)
        by_id[a["artifact_id"]] = a

    tasks_by_artifact: dict[str, list[dict]] = {}
    unmatched_tasks: list[str] = []
    for t in tasks:
        a = by_name.get(t["name"])
        if a is None:
            unmatched_tasks.append(t["name"])
            continue
        tasks_by_artifact.setdefault(a["artifact_id"], []).append(t)

    for aid, ts in tasks_by_artifact.items():
        envs = sorted({env_map.get(t["environment_id"], t["environment_id"])
                       for t in ts if t["environment_id"]})
        by_id[aid]["tmc_task"] = {
            "deployed_in_environments": envs,
            "in_prod": any(str(e).lower() in _PROD_NAMES for e in envs),
            "task_ids": sorted(t["id"] for t in ts),
            "workspace_ids": sorted({t["workspace_id"] for t in ts if t["workspace_id"]}),
            "paused_in_all": all(t["paused"] for t in ts) if ts else False,
            "runtime_type": ts[0]["runtime_type"] if ts else "",
            "provenance": "tmc",
        }

    artifacts = doc.get("artifacts", [])
    # Seed only from DEPLOYABLE artifacts that own a task: a non-deployable
    # (joblet/routine) that happens to name-match a task must not seed reachability
    # and reclassify a genuinely orphaned job as a reachable worker.
    deployed_ids = {a["artifact_id"] for a in artifacts
                    if a.get("tmc_task") and a["type"] in DEPLOYABLE_TYPES}

    # Reachability over the tRunJob call graph: a job with no task of its own is
    # not necessarily dead — it may be a worker called by a deployed parent.
    adj: dict[str, set[str]] = {}
    for a in artifacts:
        adj[a["artifact_id"]] = {
            c.get("target_artifact_id") for c in a.get("calls", [])
            if c.get("target_artifact_id") and c["target_artifact_id"] != UNRESOLVED
        }
    reachable = set(deployed_ids)
    stack = list(deployed_ids)
    while stack:
        for nxt in adj.get(stack.pop(), ()):
            if nxt not in reachable:
                reachable.add(nxt)
                stack.append(nxt)

    deployable = [a for a in artifacts if a["type"] in DEPLOYABLE_TYPES]
    deployed = [a for a in deployable if a["artifact_id"] in deployed_ids]
    via_parent = [a for a in deployable
                  if a["artifact_id"] not in deployed_ids and a["artifact_id"] in reachable]
    orphaned = [a for a in deployable if a["artifact_id"] not in reachable]

    # Per-environment deployment presence (prod is the authoritative 'runs' view).
    deployment_by_environment: dict[str, int] = {}
    for a in deployed:
        for env in a["tmc_task"]["deployed_in_environments"]:
            deployment_by_environment[env] = deployment_by_environment.get(env, 0) + 1
    prod_deployed = sum(1 for a in deployed if a["tmc_task"]["in_prod"])

    return {
        "deployable_total": len(deployable),
        "deployed": len(deployed),
        "deployed_in_prod": prod_deployed,
        "deployment_by_environment": deployment_by_environment,
        "reachable_via_parent": len(via_parent),
        "orphaned_candidates": sorted(a["name"] for a in orphaned),
        "unmatched_tasks": sorted(unmatched_tasks),
        "note": ("'deployed' = has its own TMC task (in any environment); 'in_prod' "
                 "= has a task in a prod-named environment; 'reachable_via_parent' = "
                 "worker/sub-job called by a deployed job; 'orphaned_candidates' = "
                 "neither (dead-code candidates — confirm before acting). Task↔artifact "
                 "match is by name; REST services / renamed tasks may not match."),
    }


def enrich(doc: dict, client: Optional[tc.TmcClient] = None, *,
           with_stats: bool = False, stats_window_days: int = 90,
           generated_at: str = "") -> dict:
    """Fill the doc's environments / infrastructure / tmc{} blocks and correlate.

    Mutates and returns `doc`. Read-only against TMC throughout.
    """
    client = client or tc.TmcClient()
    region = client.cfg.get("tmc.region") or tc.DEFAULT_REGION

    environments = fetch_environments(client)
    workspaces = fetch_workspaces(client)
    engines = fetch_engines(client)
    tasks = fetch_tasks(client)
    plans = fetch_plans(client)

    doc["environments"] = environments
    doc["infrastructure"]["tmc_region"] = region
    doc["infrastructure"]["workspaces"] = workspaces
    doc["infrastructure"]["engines"] = engines

    env_map = {e["id"]: e["name"] for e in environments}
    summary = correlate(doc, tasks, plans, env_map)

    stats: list[dict] = []
    if with_stats:
        for t in tasks:
            s = aggregate_task_stats(client, t["id"], stats_window_days)
            if s:
                s["task_name"] = t["name"]
                stats.append(s)

    doc["tmc"] = {
        "enriched": True, "enriched_at": generated_at, "region": region,
        "tasks": tasks, "plans": plans, "execution_stats": stats,
        "summary": summary, "requests_made": len(client.calls),
    }
    return doc
