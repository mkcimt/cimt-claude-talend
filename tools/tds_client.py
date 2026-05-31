#!/usr/bin/env python3
"""
tds_client.py — shared client for the Talend Data Stewardship (TDS) REST API.

Stdlib-only (urllib). Mirrors the kit's TMC tooling shape: config from
`.claude/*.properties` (reusing `properties.py`) with environment overrides,
Bearer-token auth, a single `request()` choke point with structured error
parsing, and a `--dry-run` switch that prints mutating requests instead of
sending them.

Config keys (in `.claude/talend.local.properties`, gitignored — or env):
    tds.base_url     full base, e.g. https://tds.eu.cloud.talend.com   (TALEND_TDS_BASE_URL)
    tds.region       region slug used if base_url unset, e.g. eu        (TALEND_TDS_REGION)
    tds.token        Bearer PAT                                         (TALEND_TDS_TOKEN)
    tds.user_email   default owner/participant username for campaigns   (TALEND_TDS_USER)

The three live API services and their path prefixes:
    data-stewardship   campaigns         /data-stewardship/api/v1/...
    schemaservice      data models       /schemaservice/api/v1/schemas/org.talend.schema/...
    semanticservice    semantic types    /semanticservice/...

See `knowledge/tds/known-gaps.md` for the live-verified capability matrix
(tasks and DQ rules have no REST endpoint).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import properties as _props  # noqa: E402

DEFAULT_REGION = "eu"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
TIMEOUT_SECONDS = 60.0


class TdsError(Exception):
    """A TDS API call failed. Carries the HTTP status and a parsed message."""

    def __init__(self, status: int | str, message: str, *, code: str | None = None,
                 method: str | None = None, url: str | None = None) -> None:
        self.status = status
        self.code = code
        self.method = method
        self.url = url
        loc = f" on {method} {url}" if url else ""
        super().__init__(f"TDS HTTP {status}{loc}: {message}"
                         + (f" [{code}]" if code else ""))


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def find_config_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (or cwd) looking for `.claude/talend.local.properties`.

    Returns the directory containing `.claude/`, or None if not found.
    """
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
    """Merge project + local `.properties`, then overlay environment variables."""
    cfg: dict[str, str] = {}
    base = root if root is not None else find_config_root()
    if base is not None:
        claude = base / ".claude"
        cfg.update(_props.load(claude / "talend.properties"))
        cfg.update(_props.load(claude / "talend.local.properties"))
    env_map = {
        "TALEND_TDS_BASE_URL": "tds.base_url",
        "TALEND_TDS_REGION": "tds.region",
        "TALEND_TDS_TOKEN": "tds.token",
        "TALEND_TDS_USER": "tds.user_email",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val
    return cfg


def base_url(cfg: dict[str, str]) -> str:
    explicit = cfg.get("tds.base_url")
    if explicit:
        return explicit.rstrip("/")
    region = cfg.get("tds.region") or DEFAULT_REGION
    return f"https://tds.{region}.cloud.talend.com"


def need_token(cfg: dict[str, str]) -> str:
    token = cfg.get("tds.token") or os.environ.get("TALEND_TDS_TOKEN")
    if not token:
        sys.exit(
            "TDS token not available. Set `tds.token` in .claude/talend.local.properties "
            "or the TALEND_TDS_TOKEN env var (a Talend Cloud Personal Access Token)."
        )
    return token


# --------------------------------------------------------------------------
# Error parsing
# --------------------------------------------------------------------------
def _extract_error(raw: str) -> tuple[str, str | None]:
    """Pull a human message + optional code out of a TDS error body.

    Handles the shapes seen live:
      {"errors":[{"code":..,"message":..}]}
      {"code":..,"message":..,"context":{..}}
      {"timestamp":..,"status":..,"error":"Not Found","path":..}
    Falls back to the raw text.
    """
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


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
class TdsClient:
    """Thin TDS REST client. One `request()` choke point; resource logic lives
    in tds_ops.py."""

    def __init__(self, cfg: dict[str, str] | None = None, *, dry_run: bool = False,
                 base: str | None = None, token: str | None = None) -> None:
        self.cfg = cfg if cfg is not None else load_config()
        self.base = (base or base_url(self.cfg)).rstrip("/")
        self.token = token if token is not None else need_token(self.cfg)
        self.dry_run = dry_run

    # -- low level -------------------------------------------------------
    def build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = self.base + (path if path.startswith("/") else "/" + path)
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        return url

    def request(self, method: str, path: str, *, body: Any = None,
                params: dict[str, Any] | None = None, accept_json: bool = True) -> Any:
        """Perform one request. Returns parsed JSON (or text). Raises TdsError on >=400.

        When dry_run is on and the method mutates, prints the request and returns
        a sentinel dict instead of sending it.
        """
        method = method.upper()
        url = self.build_url(path, params)

        if self.dry_run and method in MUTATING:
            print(f"[dry-run] {method} {url}")
            if body is not None:
                print(json.dumps(body, indent=2, ensure_ascii=False))
            return {"_dry_run": True, "method": method, "url": url, "body": body}

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if accept_json:
            req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                raw = resp.read().decode("utf-8", "replace")
                if not raw:
                    return None
                if not accept_json:
                    return raw
                try:
                    return json.loads(raw)
                except ValueError:
                    return raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            message, code = _extract_error(raw)
            raise TdsError(e.code, message, code=code, method=method, url=url) from None
        except urllib.error.URLError as e:
            raise TdsError("network", str(e.reason), method=method, url=url) from None

    # -- sugar -----------------------------------------------------------
    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.request("POST", path, body=body, **kw)

    def put(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.request("PUT", path, body=body, **kw)

    def patch(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.request("PATCH", path, body=body, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)


def as_list(data: Any) -> list:
    """Normalize a list response: a bare JSON array, or a {items|content|elements:[…]} wrapper."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "content", "elements", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return [data]
