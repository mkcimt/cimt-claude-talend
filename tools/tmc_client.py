#!/usr/bin/env python3
"""
tmc_client.py — a strictly READ-ONLY client for the Talend Management Console
(TMC / Talend Cloud) Public API, used by the project-intake enrichment (phase 3)
to read TMC state without ever mutating the customer's environment.

╔══════════════════════════════════════════════════════════════════════════╗
║  READ-ONLY BY CONSTRUCTION                                                 ║
║                                                                            ║
║  • The only public verb is `get()`. There is no post/put/patch/delete —    ║
║    no code path in this module issues a mutating request.                  ║
║  • Every request funnels through `_request()`, which RAISES                 ║
║    `TmcReadOnlyViolation` on any method other than GET (belt + suspenders). ║
║  • Requests are restricted to an allow-list of read API products; a path    ║
║    outside it is refused before any network call.                          ║
║  • Every call is recorded in `self.calls` so an engagement can show         ║
║    exactly what was queried.                                                ║
║                                                                            ║
║  A TMC PAT carries its owner's FULL permissions — TMC PATs are not          ║
║  read-scoped. The read-only guarantee therefore lives HERE, in this code,   ║
║  not in the token. For production, provision the PAT from a TMC service     ║
║  account with a read-only role as defence in depth.                         ║
╚══════════════════════════════════════════════════════════════════════════╝

Config (in .claude/talend.local.properties, gitignored — or env):
    tmc.region   region slug, e.g. eu   (TALEND_TMC_REGION)  -> base api.<region>.cloud.talend.com
    tmc.base_url full base override                          (TALEND_TMC_BASE_URL)
    tmc.pat      Bearer PAT             (TALEND_PAT)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import properties as _props  # noqa: E402

DEFAULT_REGION = "eu"
TIMEOUT_SECONDS = 60.0

# Defence-in-depth allow-list: only the *read* API products the intake needs.
# A path that does not start with one of these is refused before any network I/O.
ALLOWED_PREFIXES = (
    "/orchestration/",          # environments, workspaces, tasks, plans (read)
    "/processing/",             # engines, run-profiles, execution status (read)
    "/observability/",          # run-time metrics (read)
    "/execution-history/",      # execution history search (read)
    "/monitoring/",             # monitoring (read)
    "/audit/",                  # audit logs (read)
)


class TmcReadOnlyViolation(RuntimeError):
    """Raised if anything ever attempts a non-GET request through this client.

    This should never happen in normal use — it exists to make a read-only
    violation a hard, loud failure rather than a silent mutation.
    """


class TmcError(Exception):
    """A TMC API GET failed. Carries the HTTP status and a parsed message."""

    def __init__(self, status: int | str, message: str, *, code: str | None = None,
                 url: str | None = None) -> None:
        self.status = status
        self.code = code
        self.url = url
        loc = f" on GET {url}" if url else ""
        super().__init__(f"TMC HTTP {status}{loc}: {message}" + (f" [{code}]" if code else ""))


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def find_config_root(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    while True:
        if (cur / ".claude" / "talend.local.properties").is_file():
            return cur
        if (cur / ".claude" / "talend.properties").is_file():
            return cur
        if cur == cur.parent:
            return None
        cur = cur.parent


def load_config(root: Path | None = None) -> dict[str, str]:
    cfg: dict[str, str] = {}
    base = root if root is not None else find_config_root()
    if base is not None:
        claude = base / ".claude"
        cfg.update(_props.load(claude / "talend.properties"))
        cfg.update(_props.load(claude / "talend.local.properties"))
    env_map = {
        "TALEND_TMC_BASE_URL": "tmc.base_url",
        "TALEND_TMC_REGION": "tmc.region",
        "TALEND_PAT": "tmc.pat",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val
    return cfg


def base_url(cfg: dict[str, str]) -> str:
    explicit = cfg.get("tmc.base_url")
    if explicit:
        return explicit.rstrip("/")
    region = cfg.get("tmc.region") or DEFAULT_REGION
    return f"https://api.{region}.cloud.talend.com"


def need_token(cfg: dict[str, str]) -> str:
    token = cfg.get("tmc.pat") or os.environ.get("TALEND_PAT")
    if not token:
        sys.exit(
            "TMC token not available. Set `tmc.pat` in .claude/talend.local.properties "
            "or the TALEND_PAT env var (a Talend Cloud Personal Access Token). "
            "For intake, a service account with a read-only role is recommended."
        )
    return token


def _extract_error(raw: str) -> tuple[str, str | None]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return (raw.strip()[:300] or "(empty body)"), None
    if isinstance(data, dict):
        if isinstance(data.get("errors"), list) and data["errors"]:
            first = data["errors"][0]
            if isinstance(first, dict):
                return first.get("message") or json.dumps(first), first.get("code")
        if data.get("message"):
            return str(data["message"]), data.get("code")
        if data.get("error"):
            return str(data["error"]), str(data.get("status") or "")
    return json.dumps(data)[:300], None


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class TmcClient:
    """Read-only TMC REST client. `get()` is the only verb."""

    def __init__(self, cfg: dict[str, str] | None = None, *,
                 base: str | None = None, token: str | None = None,
                 audit: bool = True) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self.base = (base or base_url(self.cfg)).rstrip("/")
        self.token = token if token is not None else need_token(self.cfg)
        self.calls: list[dict[str, Any]] = []
        self._audit = audit

    # -- guards ----------------------------------------------------------- #
    @staticmethod
    def _ensure_get(method: str) -> None:
        if method.upper() != "GET":
            raise TmcReadOnlyViolation(
                f"tmc_client is read-only; refused a {method.upper()} request. "
                "This client must never mutate TMC."
            )

    @staticmethod
    def _ensure_allowed(path: str) -> None:
        p = path if path.startswith("/") else "/" + path
        if not p.startswith(ALLOWED_PREFIXES):
            raise TmcReadOnlyViolation(
                f"path {p!r} is not in the read-only allow-list {ALLOWED_PREFIXES}. "
                "Add it deliberately if it is a genuine read endpoint."
            )

    def build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self.base + (path if path.startswith("/") else "/" + path)
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        return url

    # -- the single choke point ------------------------------------------ #
    def _request(self, method: str, path: str,
                 params: dict[str, Any] | None = None) -> Any:
        # Two hard guards before any network I/O.
        self._ensure_get(method)
        self._ensure_allowed(path)
        url = self.build_url(path, params)
        # Explicit GET, no body — urllib cannot mutate without data + a verb.
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")
        status: Any = "?"
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            status = e.code
            message, code = _extract_error(e.read().decode("utf-8", "replace"))
            raise TmcError(e.code, message, code=code, url=url) from None
        except urllib.error.URLError as e:
            status = "network"
            raise TmcError("network", str(e.reason), url=url) from None
        finally:
            if self._audit:
                self.calls.append({"method": "GET", "url": url, "status": status})

    # -- the only public verb -------------------------------------------- #
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue a read-only GET and return parsed JSON."""
        return self._request("GET", path, params)

    def get_all(self, path: str, params: dict[str, Any] | None = None,
                *, items_key: str | None = None, page_size: int = 100,
                max_pages: int = 1000) -> list[Any]:
        """GET a (possibly paginated) list endpoint and return all items.

        Handles the common TMC shapes: a bare JSON array, or an object whose
        items live under `items`/`data`/`content` with offset/limit paging.
        Read-only throughout; stops at `max_pages` to avoid runaway loops.
        """
        out: list[Any] = []
        params = dict(params or {})
        offset = 0
        for _ in range(max_pages):
            page_params = dict(params)
            page_params.setdefault("limit", page_size)
            page_params["offset"] = offset
            data = self.get(path, page_params)
            if data is None:
                break
            if isinstance(data, list):
                batch = data
            elif isinstance(data, dict):
                key = items_key or next(
                    (k for k in ("items", "data", "content", "results") if k in data), None)
                batch = data.get(key, []) if key else []
            else:
                batch = []
            out.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return out


if __name__ == "__main__":
    # OFFLINE self-test — proves the read-only guard without any network I/O.
    c = TmcClient(cfg={"tmc.region": "eu"}, token="dummy", base="https://api.eu.cloud.talend.com")

    # 1) Any non-GET method is refused, before any network call.
    for verb in ("POST", "PUT", "PATCH", "DELETE", "post", "Delete"):
        try:
            c._request(verb, "/orchestration/environments")
            raise SystemExit(f"FAIL: {verb} was not refused")
        except TmcReadOnlyViolation:
            pass

    # 2) A path outside the read allow-list is refused.
    try:
        c.get("/some/random/write/endpoint")
        raise SystemExit("FAIL: off-allowlist path was not refused")
    except TmcReadOnlyViolation:
        pass

    # 3) URL building is correct and params are encoded.
    assert c.build_url("/orchestration/environments") == "https://api.eu.cloud.talend.com/orchestration/environments"
    assert c.build_url("orchestration/tasks", {"limit": 50, "skip": None}) == \
        "https://api.eu.cloud.talend.com/orchestration/tasks?limit=50"

    # 4) base_url derivation + token requirement.
    assert base_url({"tmc.region": "us"}) == "https://api.us.cloud.talend.com"
    assert base_url({"tmc.base_url": "https://x/"}) == "https://x"

    # 5) Meta-guarantee: every urllib Request built in this module uses GET.
    #    (Scoped to .Request(...) calls so guard-set / doc text mentioning other
    #    verbs doesn't trip it.)
    import re
    src = Path(__file__).read_text()
    request_verbs = re.findall(r'\.Request\([^)]*?method\s*=\s*["\'](\w+)["\']', src)
    assert request_verbs and set(request_verbs) == {"GET"}, \
        f"a non-GET urllib Request exists in tmc_client.py: {request_verbs}"

    print("tmc_client.py self-test passed (read-only guards verified, offline)")
