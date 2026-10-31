#!/usr/bin/env python3
"""Optional connections for Agent City jobs. Every one is OFF until you add its repo secret.

Jobs run on GitHub's servers, so they can't borrow the connectors on your claude.ai account.
Each service gets its own key, stored under Settings > Secrets and variables > Actions:

  FIRECRAWL_API_KEY   web search + page scraping tools for standard/heavy agents (firecrawl.dev)
  CITY_MCP_SERVERS    JSON for any other remote MCP servers, for example:
                      {"alpha": {"type": "http", "url": "https://mcp.example.com/mcp",
                                 "headers": {"Authorization": "Bearer KEY"}}}
  SLACK_WEBHOOK_URL   posts "job done / paused / failed" messages to a Slack channel

Nothing here ever runs a model, and nothing is written to the repo: the MCP config lives only in the
runner's temp folder, because it can contain keys.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

TMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
SLACK_PREFIX = "https://hooks.slack.com/"


def _clean(name: str) -> str:
    return re.sub(r"\s+", "", os.environ.get(name, "") or "")


def mcp_setup() -> tuple[Path | None, list[str]]:
    """Return (config file, allowed-tool patterns) for the connections that have a secret, else (None, [])."""
    servers: dict[str, dict] = {}

    key = _clean("FIRECRAWL_API_KEY")
    if key:
        servers["firecrawl"] = {"command": "npx", "args": ["-y", "firecrawl-mcp"],
                                "env": {"FIRECRAWL_API_KEY": key}}

    raw = (os.environ.get("CITY_MCP_SERVERS") or "").strip()
    if raw:
        try:
            extra = json.loads(raw)
            assert isinstance(extra, dict)
        except Exception:  # noqa: BLE001
            print("CITY_MCP_SERVERS is not valid JSON; ignoring it", file=sys.stderr)
            extra = {}
        for name, conf in extra.items():
            if not NAME_OK.match(str(name)) or not isinstance(conf, dict):
                print(f"skipping MCP server with a bad name or config: {str(name)[:40]!r}", file=sys.stderr)
                continue
            # only remote servers: a secret should not be able to make the runner execute arbitrary commands
            if conf.get("type") not in ("http", "sse") or not str(conf.get("url", "")).startswith("https://"):
                print(f"skipping MCP server {name!r}: needs type http/sse and an https:// url", file=sys.stderr)
                continue
            servers.setdefault(name, conf)

    if not servers:
        return None, []
    path = TMP / "city-mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}))
    path.chmod(0o600)
    print("connections on for this job: " + ", ".join(sorted(servers)))   # names only, never keys
    return path, [f"mcp__{name}" for name in servers]


def notify(text: str) -> None:
    """Post to Slack if SLACK_WEBHOOK_URL is set. Never raises: an alert must not fail a job."""
    url = _clean("SLACK_WEBHOOK_URL")
    if not url:
        return
    if not url.startswith(SLACK_PREFIX):
        print("SLACK_WEBHOOK_URL does not look like a Slack webhook; skipping alert", file=sys.stderr)
        return
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": text[:3000]}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # noqa: BLE001
        print(f"Slack alert failed: {type(e).__name__}", file=sys.stderr)
