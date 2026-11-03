"""Optional Charles Schwab market data (READ-ONLY). Switches on only when these GitHub secrets exist:

    SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_REFRESH_TOKEN

Used for: real-time quotes (to verify every price before a paper trade) and real option chains.
This module never touches the Trader (order) API, and nothing in the project can place an order.
Schwab refresh tokens expire after 7 days; when that happens this reports it and the floor falls back
to the free sources until you run `python3 scripts/schwab_auth.py` again.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
from datetime import date, timedelta

from . import sources
from .options import parse_schwab_chain

BASE = "https://api.schwabapi.com"


def parse_quotes(raw: dict) -> dict:
    out = {}
    for sym, v in (raw or {}).items():
        q = (v or {}).get("quote") or {}
        last = q.get("lastPrice") or q.get("mark")
        if not last:
            continue
        t = q.get("quoteTime") or q.get("tradeTime")
        out[sym] = {"last": float(last), "bid": q.get("bidPrice"), "ask": q.get("askPrice"), "time": (t / 1000.0) if t else None,
                    "chg_pct": q.get("netPercentChange"), "volume": q.get("totalVolume")}
    return out


class SchwabClient:
    def __init__(self, key, secret, refresh):
        self.key, self.secret, self.refresh = key, secret, refresh
        self._tok, self._exp = None, 0.0

    @classmethod
    def from_env(cls):
        k, s, r = (os.environ.get(x, "").strip() for x in ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "SCHWAB_REFRESH_TOKEN"))
        return cls(k, s, r) if k and s and r else None

    def token(self) -> str:
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        basic = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": self.refresh}).encode()
        try:
            res = json.loads(sources.http_post(f"{BASE}/v1/oauth/token", body, {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("Schwab sign-in failed (refresh token expired after 7 days? run scripts/schwab_auth.py): " + str(e)[:100])
        self._tok = res["access_token"]
        self._exp = time.time() + float(res.get("expires_in", 1800))
        return self._tok

    def _get(self, path, params):
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        return json.loads(sources.http_get(url, timeout=20, retries=1, headers={"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}))

    def quotes(self, symbols):
        return parse_quotes(self._get("/marketdata/v1/quotes", {"symbols": ",".join(symbols), "fields": "quote"}))

    def chain(self, symbol, today: date | None = None):
        today = today or date.today()
        raw = self._get("/marketdata/v1/chains", {"symbol": symbol, "contractType": "ALL", "strikeCount": 12, "includeUnderlyingQuote": "false",
                                                  "fromDate": (today + timedelta(days=20)).isoformat(), "toDate": (today + timedelta(days=75)).isoformat()})
        return parse_schwab_chain(raw)
