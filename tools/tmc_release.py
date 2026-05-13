#!/usr/bin/env python3
"""
TMC release CLI — build, publish, bind, promote, deploy a single Talend
microservice (or any artifact) by name.

All TMC IDs (artifact, workspace, task, promotion) are auto-discovered
from the API name and env names; the user never types an ID.

Configuration — two layers:

  1. Project: <project-root>/.claude/talend.config.json (committed).
     Auto-discovered by walking up from CWD.

  2. Dev / machine: env vars (typically set by .claude/settings.local.json):
        TALEND_STUDIO_PATH    — path to Talend Studio install
        JAVA_HOME             — JDK 17 (Studio's bundled Zulu is fine)
        TALEND_PAT            — TMC personal access token
        TALEND_USER_COMPONENTS_FOLDER (optional, only for builds)

Usage:

    tmc_release.py status <api>
    tmc_release.py genpoms
    tmc_release.py build <api>
    tmc_release.py publish <api> [--env dev]
    tmc_release.py bind   <api> --env dev
    tmc_release.py promote <api> --src dev --dst tst
    tmc_release.py deploy <api> --env tst
    tmc_release.py release <api> --src dev --dst tst
        # full chain: build + publish to src + bind src + promote src->dst + deploy on dst

Exit code 0 = success; non-zero = something failed (fail-fast — no best-effort).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- config ---


def find_project_root(start: Path | None = None) -> Path:
    """Walk up looking for .claude/talend.config.json."""
    cur = (start or Path.cwd()).resolve()
    while cur != cur.parent:
        if (cur / ".claude" / "talend.config.json").is_file():
            return cur
        cur = cur.parent
    sys.exit(
        "Could not find .claude/talend.config.json walking up from "
        f"{start or Path.cwd()}. Are you inside a Talend project that uses "
        "the cimt-talend plugin?"
    )


def load_config(root: Path) -> dict:
    return json.loads((root / ".claude" / "talend.config.json").read_text("utf-8"))


def need_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"Required env var {name} is not set.")
    return v


# ----------------------------------------------------------------- http ---


def api_base(cfg: dict) -> str:
    region = cfg["tmc"].get("region", "eu")
    return f"https://api.{region}.cloud.talend.com"


def http(method: str, url: str, *, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", "replace")
        sys.exit(f"HTTP {e.code} on {method} {url}\n{body_text}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error on {method} {url}: {e}")


# ---------------------------------------------------------- discovery ----


def discover_artifact(cfg: dict, name: str, env: str, token: str) -> dict:
    """Return the artifact dict {id, workspace.id, versions[0]} for env."""
    base = api_base(cfg)
    q = urllib.parse.urlencode({"name": name})
    data = http("GET", f"{base}/orchestration/artifacts?{q}", token=token)
    for it in data.get("items", []):
        if (
            it["name"] == name
            and it["workspace"]["environment"]["name"] == env
        ):
            return it
    sys.exit(f"No artifact named {name!r} found in env {env!r}")


def discover_task(cfg: dict, artifact: dict, token: str) -> dict:
    base = api_base(cfg)
    q = urllib.parse.urlencode(
        {"workspaceId": artifact["workspace"]["id"], "artifactId": artifact["id"]}
    )
    data = http(
        "GET", f"{base}/orchestration/executables/tasks?{q}", token=token
    )
    items = data.get("items", [])
    if not items:
        sys.exit(
            f"No task found for artifact {artifact['name']} "
            f"in env {artifact['workspace']['environment']['name']}"
        )
    if len(items) > 1:
        sys.exit(
            f"Multiple tasks found for artifact {artifact['name']} — "
            f"can't pick one automatically: {[t['executable'] for t in items]}"
        )
    return items[0]


def discover_promotion(cfg: dict, src: str, dst: str, token: str) -> dict:
    base = api_base(cfg)
    data = http("GET", f"{base}/orchestration/executables/promotions", token=token)
    for p in data:
        if (
            p["sourceEnvironment"]["name"] == src
            and p["targetEnvironment"]["name"] == dst
        ):
            return p
    sys.exit(
        f"No promotion definition found for {src} -> {dst}. "
        "Create one in TMC first (Promotions menu)."
    )


# -------------------------------------------------------- maven helpers ---


def maven_args(cfg: dict, project_root: Path) -> list[str]:
    """The repeatable -s / -D... block for any maven invocation."""
    studio = need_env("TALEND_STUDIO_PATH")
    return [
        "-B",
        "-s", f"{studio}/configuration/maven_user_settings.xml",
        f"-Dmaven.repo.local={studio}/configuration/.m2/repository",
        f"-Dlicense.path={studio}/license",
        f"-Dtalend.studio.p2.update={cfg['p2UpdateUrl']}",
        "-Dgeneration.type=local",
        "-Dstudio.error.on.component.missing=false",
    ]


def find_api_pom(project_root: Path, project_name: str, api_name: str) -> Path:
    """Locate the highest-version pom for an API under poms/jobs/process/.

    Walks the i5xx_apis convention but falls back to a plain glob across
    process/ subtrees so non-i5xx artifacts work too.
    """
    poms = project_root / project_name / "poms" / "jobs" / "process"
    candidates: list[Path] = list(poms.glob(f"i5xx_apis/{api_name}/{api_name}_*/pom.xml"))
    if not candidates:
        candidates = list(poms.glob(f"**/{api_name}/{api_name}_*/pom.xml"))
    if not candidates:
        # Fallback for items whose parent folder name differs from the artifact
        # name (e.g. i5xx_api_<resource> lives under i5xx_<resource>/).
        candidates = list(poms.glob(f"**/{api_name}_*/pom.xml"))
    if not candidates:
        sys.exit(
            f"Could not locate pom.xml for {api_name} under {poms}. "
            "Did `tmc_release.py genpoms` run?"
        )
    candidates.sort(key=lambda p: p.parent.name)
    return candidates[-1]  # highest version directory name (lexicographic for x.y)


def run_mvn(args: list[str], cwd: Path) -> None:
    """Run `mvn` in cwd, streaming output. Exit on non-zero."""
    cmd = ["mvn", *args]
    print(f"+ (cd {cwd}; {' '.join(cmd)})", file=sys.stderr)
    rc = subprocess.call(cmd, cwd=str(cwd))
    if rc != 0:
        sys.exit(f"mvn exited with {rc}")


# ----------------------------------------------------------- commands ----


def cmd_status(cfg: dict, args, token: str) -> int:
    base = api_base(cfg)
    q = urllib.parse.urlencode({"name": args.api})
    data = http("GET", f"{base}/orchestration/artifacts?{q}", token=token)
    print(f"{args.api}:")
    for it in data.get("items", []):
        if it["name"] != args.api:
            continue
        env = it["workspace"]["environment"]["name"]
        ver = it["versions"][0] if it["versions"] else "(no versions)"
        # find task pinned to this artifact in this workspace
        try:
            task = discover_task(cfg, it, token)
            full = http(
                "GET",
                f"{base}/orchestration/executables/tasks/{task['executable']}",
                token=token,
            )
            bound = full["artifact"]["version"]
        except SystemExit:
            bound = "(no task)"
        print(f"  {env:>4}: latest={ver} | task bound to={bound}")
    return 0


def cmd_genpoms(cfg: dict, args, token: str, project_root: Path) -> int:
    run_mvn(
        [
            "org.talend.ci:builder-maven-plugin:8.0.27:generateAllPoms",
            *maven_args(cfg, project_root),
            "-N",
        ],
        cwd=project_root,
    )
    return 0


def cmd_build(cfg: dict, args, token: str, project_root: Path) -> int:
    pom = find_api_pom(project_root, cfg["talendProjectName"], args.api)
    poms_root = project_root / cfg["talendProjectName"] / "poms"
    pl = pom.parent.relative_to(poms_root).as_posix()
    run_mvn(
        ["clean", "package", *maven_args(cfg, project_root), "-pl", pl, "-am", "-fae"],
        cwd=poms_root,
    )
    return 0


def cmd_publish(cfg: dict, args, token: str, project_root: Path) -> int:
    pom = find_api_pom(project_root, cfg["talendProjectName"], args.api)
    poms_root = project_root / cfg["talendProjectName"] / "poms"
    pl = pom.parent.relative_to(poms_root).as_posix()
    studio = need_env("TALEND_STUDIO_PATH")
    run_mvn(
        [
            "org.talend.ci:cloudpublisher-maven-plugin:8.0.13:publish",
            "-B",
            "-s", f"{studio}/configuration/maven_user_settings.xml",
            f"-Dmaven.repo.local={studio}/configuration/.m2/repository",
            f"-Dservice.url={cfg['tmc']['publishUrl']}",
            f"-Dcloud.token={token}",
            f"-Dcloud.publisher.workspace={cfg['tmc']['workspace']}",
            f"-Dcloud.publisher.environment={args.env}",
            "-Dcloud.publisher.screenshot=true",
            "-pl", pl,
        ],
        cwd=poms_root,
    )
    return 0


def cmd_bind(cfg: dict, args, token: str) -> int:
    base = api_base(cfg)
    art = discover_artifact(cfg, args.api, args.env, token)
    ver = art["versions"][0]
    task = discover_task(cfg, art, token)
    task_id = task["executable"]
    full = http("GET", f"{base}/orchestration/executables/tasks/{task_id}", token=token)
    pre_rc = http(
        "GET", f"{base}/orchestration/executables/tasks/{task_id}/run-config",
        token=token,
    )
    body = {k: v for k, v in full.items() if k not in ("workspace", "version", "id")}
    body["workspaceId"] = full["workspace"]["id"]
    body["artifact"] = {"id": full["artifact"]["id"], "version": ver}
    res = http(
        "PUT", f"{base}/orchestration/executables/tasks/{task_id}",
        token=token, body=body,
    )
    # Talend bug (verified 2026-05-09): a real artifact-version change on the
    # task body silently sets microservicePort to null on /run-config.
    # No-op binds (same version) are unaffected. Restore the pre-bind run-config
    # to keep the port (and any other run-config field) stable.
    rc_restore = {k: v for k, v in pre_rc.items() if k != "lineage"}
    http(
        "PUT", f"{base}/orchestration/executables/tasks/{task_id}/run-config",
        token=token, body=rc_restore,
    )
    print(
        f"{args.api} on {args.env}: task {res['version']} now bound to "
        f"{res['artifact']['version']} (run-config restored)"
    )
    return 0


def cmd_promote(cfg: dict, args, token: str) -> dict:
    base = api_base(cfg)
    art_src = discover_artifact(cfg, args.api, args.src, token)
    task_src = discover_task(cfg, art_src, token)
    prom = discover_promotion(cfg, args.src, args.dst, token)
    body = {
        "executable": prom["executable"],
        "advanced": {"artifactId": task_src["executable"], "artifactType": "FLOW"},
        "context": f"{args.api} {args.src}->{args.dst} via cimt-talend plugin",
    }
    res = http(
        "POST", f"{base}/processing/executions/promotions",
        token=token, body=body,
    )
    er = res.get("executionReport", res)
    target_id = None
    for w in er.get("workspaces", []):
        for f in w.get("flows", []):
            if f.get("id") == task_src["executable"]:
                target_id = f.get("targetId")
                break
    print(f"{args.api}: promoted {args.src}->{args.dst} status={er.get('status')} targetTask={target_id}")
    if not target_id:
        sys.exit("Promotion succeeded but no targetId returned — cannot continue.")
    return {"target_task": target_id}


def cmd_deploy(cfg: dict, args, token: str, *, task_id: str | None = None) -> int:
    base = api_base(cfg)
    if not task_id:
        art = discover_artifact(cfg, args.api, args.env, token)
        task = discover_task(cfg, art, token)
        task_id = task["executable"]
    res = http(
        "POST", f"{base}/processing/executions",
        token=token, body={"executable": task_id},
    )
    print(f"{args.api}: executionId={res.get('executionId')}")
    return 0


def cmd_release(cfg: dict, args, token: str, project_root: Path) -> int:
    """Full chain: build + publish to src + bind src + promote src->dst + deploy on dst."""
    sub = argparse.Namespace(api=args.api, env=args.src)
    cmd_build(cfg, sub, token, project_root)
    cmd_publish(cfg, sub, token, project_root)
    cmd_bind(cfg, sub, token)
    prom_res = cmd_promote(cfg, args, token)
    sub_dst = argparse.Namespace(api=args.api, env=args.dst)
    cmd_deploy(cfg, sub_dst, token, task_id=prom_res["target_task"])
    return 0


# -------------------------------------------------------------- main ----


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s_status = sub.add_parser("status")
    s_status.add_argument("api")

    sub.add_parser("genpoms")

    s_build = sub.add_parser("build")
    s_build.add_argument("api")

    s_pub = sub.add_parser("publish")
    s_pub.add_argument("api")
    s_pub.add_argument("--env", default="dev")

    s_bind = sub.add_parser("bind")
    s_bind.add_argument("api")
    s_bind.add_argument("--env", required=True)

    s_prom = sub.add_parser("promote")
    s_prom.add_argument("api")
    s_prom.add_argument("--src", required=True)
    s_prom.add_argument("--dst", required=True)

    s_dep = sub.add_parser("deploy")
    s_dep.add_argument("api")
    s_dep.add_argument("--env", required=True)

    s_rel = sub.add_parser("release")
    s_rel.add_argument("api")
    s_rel.add_argument("--src", required=True)
    s_rel.add_argument("--dst", required=True)

    args = p.parse_args()

    project_root = find_project_root()
    cfg = load_config(project_root)
    token = need_env("TALEND_PAT") if args.cmd != "genpoms" or True else ""
    # genpoms doesn't strictly need the PAT but loading it eagerly is fine.

    if args.cmd == "status":
        return cmd_status(cfg, args, token)
    if args.cmd == "genpoms":
        return cmd_genpoms(cfg, args, token, project_root)
    if args.cmd == "build":
        return cmd_build(cfg, args, token, project_root)
    if args.cmd == "publish":
        return cmd_publish(cfg, args, token, project_root)
    if args.cmd == "bind":
        return cmd_bind(cfg, args, token)
    if args.cmd == "promote":
        cmd_promote(cfg, args, token)
        return 0
    if args.cmd == "deploy":
        return cmd_deploy(cfg, args, token)
    if args.cmd == "release":
        return cmd_release(cfg, args, token, project_root)
    sys.exit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
