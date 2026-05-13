#!/usr/bin/env python3
"""
TMC microservice ops — list / undeploy / redeploy all i5xx APIs in an env.

Usage:
    python tmc_microservice_ops.py list      --env dev|tst|uat|prd
    python tmc_microservice_ops.py undeploy  --env dev|tst        [--dry-run]
    python tmc_microservice_ops.py redeploy  --env dev|tst        [--dry-run]
    python tmc_microservice_ops.py cycle     --env dev|tst        [--dry-run]
        # cycle = undeploy + redeploy

Destructive ops (undeploy / redeploy / cycle) are HARD-LIMITED to dev + tst.
For uat / prd use the TMC UI — see cimt-talend/docs/tmc-task-management.md.

Requires TALEND_PAT env var.

Endpoints used (verified 2026-05-08):
- GET    /orchestration/executables/tasks?name=i5&environmentId={envId}
        -> list tasks by name-prefix + env, returns items[].executable + .runtime
- GET    /processing/executables/tasks/{taskId}/executions
        -> list executions for a task; status='executing' = currently deployed microservice
- DELETE /processing/executions/{executionId}
        -> undeploy microservice / terminate batch execution
- POST   /processing/executions  body={"executable": taskId}
        -> deploy microservice / trigger batch execution
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.eu.cloud.talend.com"
NAME_PREFIX = "i5"

ENV_IDS = {
    "dev": "6357988f877a3e106ea2361d",
    "tst": "635a77dd5b944668d2c26757",
    "uat": "64c23efba65bb12db90c7896",
    "prd": "65166dd1dc25a13f327aef3b",
}

WRITE_ALLOWED_ENVS = {"dev", "tst"}  # hard whitelist; uat/prd via UI only


def http(method: str, url: str, *, token: str, body: dict | None = None,
         accept: str = "application/json") -> tuple[bool, dict | str]:
    """Returns (ok, data). data is parsed JSON if accept=json, raw text otherwise."""
    data_bytes = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data_bytes, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    if data_bytes is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            if accept == "application/json":
                return True, (json.loads(raw) if raw else {})
            return True, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", "replace")
        print(f"  ERROR HTTP {e.code} on {method} {url}: {body_text[:300]}", file=sys.stderr)
        return False, {}
    except urllib.error.URLError as e:
        print(f"  ERROR network {method} {url}: {e}", file=sys.stderr)
        return False, {}


def list_tasks(env_id: str, token: str) -> list[dict]:
    q = urllib.parse.urlencode({"name": NAME_PREFIX, "environmentId": env_id})
    ok, data = http("GET", f"{BASE}/orchestration/executables/tasks?{q}", token=token)
    if not ok:
        return []
    return sorted(data.get("items", []), key=lambda t: t["name"])


def list_executions(task_id: str, token: str) -> list[dict]:
    ok, data = http("GET", f"{BASE}/processing/executables/tasks/{task_id}/executions",
                    token=token)
    return data.get("items", []) if ok else []


def running_executions(execs: list[dict]) -> list[dict]:
    """Microservice is 'deployed' while execution is in 'executing' or 'dispatching'."""
    return [e for e in execs if e.get("status") in ("executing", "dispatching")]


def undeploy_execution(execution_id: str, token: str) -> bool:
    """DELETE /processing/executions/{id} undeploys microservice / kills batch run.
    Note: this endpoint returns text/plain, not JSON."""
    ok, _ = http("DELETE", f"{BASE}/processing/executions/{execution_id}",
                 token=token, accept="text/plain")
    return ok


def deploy_task(task_id: str, token: str) -> str | None:
    ok, res = http("POST", f"{BASE}/processing/executions",
                   token=token, body={"executable": task_id})
    return res.get("executionId") if ok else None


def cmd_list(env: str, token: str) -> int:
    tasks = list_tasks(ENV_IDS[env], token)
    print(f"=== {env}: {len(tasks)} i5xx tasks ===\n")
    print(f"{'API':<40} {'TaskId':<26} {'#Exec':>5}  {'Latest status':<22}")
    print("-" * 100)
    for t in tasks:
        execs = list_executions(t["executable"], token)
        latest = execs[0]["status"] if execs else "-"
        print(f"{t['name']:<40} {t['executable']:<26} {len(execs):>5}  {latest:<22}")
    return 0


def _guard_destructive(env: str) -> None:
    if env not in WRITE_ALLOWED_ENVS:
        sys.exit(f"Refusing destructive op on {env!r}. "
                 f"Allowed: {sorted(WRITE_ALLOWED_ENVS)}. Use TMC UI for uat/prd.")


def cmd_undeploy(env: str, token: str, dry_run: bool) -> int:
    _guard_destructive(env)
    tasks = list_tasks(ENV_IDS[env], token)
    print(f"{'[DRY RUN] ' if dry_run else ''}Undeploying running microservices on {env} "
          f"({len(tasks)} tasks)\n")

    summary: list[tuple[str, str]] = []
    for t in tasks:
        execs = list_executions(t["executable"], token)
        running = running_executions(execs)
        if not running:
            print(f"--- {t['name']}: not running, skip")
            summary.append((t["name"], "skip (not running)"))
            continue

        print(f"--- {t['name']}: {len(running)} running execution(s)")
        if dry_run:
            for e in running:
                print(f"    [dry-run] would DELETE {e['executionId']}")
            summary.append((t["name"], f"dry-run ({len(running)})"))
            continue

        ok = 0
        for e in running:
            print(f"    DELETE {e['executionId']} ...")
            if undeploy_execution(e["executionId"], token):
                ok += 1
        summary.append((t["name"], f"undeployed {ok}/{len(running)}"))

    print("\n=== Summary ===")
    for name, status in summary:
        print(f"  {name:<40} {status}")
    return 0


def cmd_redeploy(env: str, token: str, dry_run: bool) -> int:
    _guard_destructive(env)
    tasks = list_tasks(ENV_IDS[env], token)
    print(f"{'[DRY RUN] ' if dry_run else ''}Redeploying microservices on {env} "
          f"({len(tasks)} tasks)\n")

    summary: list[tuple[str, str]] = []
    for t in tasks:
        print(f"--- {t['name']}")
        if dry_run:
            print(f"    [dry-run] would POST executions executable={t['executable']}")
            summary.append((t["name"], "dry-run"))
            continue
        eid = deploy_task(t["executable"], token)
        if eid:
            print(f"    deployed -> {eid}")
            summary.append((t["name"], f"OK {eid}"))
        else:
            summary.append((t["name"], "FAIL"))

    print("\n=== Summary ===")
    for name, status in summary:
        print(f"  {name:<40} {status}")
    return 0


def cmd_cycle(env: str, token: str, dry_run: bool) -> int:
    rc = cmd_undeploy(env, token, dry_run)
    if rc != 0:
        return rc
    if not dry_run:
        time.sleep(5)  # let the engine release the ports
    return cmd_redeploy(env, token, dry_run)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for c in ("list", "undeploy", "redeploy", "cycle"):
        sp = sub.add_parser(c)
        sp.add_argument("--env", required=True, choices=list(ENV_IDS))
        if c != "list":
            sp.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    token = os.environ.get("TALEND_PAT")
    if not token:
        sys.exit("TALEND_PAT env var is not set.")

    if args.cmd == "list":
        return cmd_list(args.env, token)
    if args.cmd == "undeploy":
        return cmd_undeploy(args.env, token, args.dry_run)
    if args.cmd == "redeploy":
        return cmd_redeploy(args.env, token, args.dry_run)
    if args.cmd == "cycle":
        return cmd_cycle(args.env, token, args.dry_run)
    return 2


if __name__ == "__main__":
    sys.exit(main())
