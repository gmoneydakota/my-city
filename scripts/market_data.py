#!/usr/bin/env python3
"""Fresh daily price history with no API key and no third-party packages.

Primary source: Yahoo Finance chart endpoint. Fallback: Stooq CSV.

Use it from other scripts:
    from market_data import fetch_history
    bars = fetch_history("NVDA", years=2)   # list of dicts, oldest first

Or from the command line (agents use this so they never guess prices):
    python3 scripts/market_data.py NVDA                 # latest quote summary
    python3 scripts/market_data.py NVDA --years 5 --csv outputs/job-7/nvda.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64) AgentCity/1.0"
TIMEOUT = 20


class DataError(RuntimeError):
    pass


def _get(url: str) -> bytes:
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise DataError(f"request failed: {url} ({last})")


def _yahoo(symbol: str, years: int) -> list[dict]:
    rng = {1: "1y", 2: "2y", 5: "5y", 10: "10y"}.get(years, "max" if years > 10 else "5y")
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(symbol)}?range={rng}&interval=1d&includeAdjustedClose=true"
    )
    data = json.loads(_get(url))
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        err = (data.get("chart") or {}).get("error")
        raise DataError(f"yahoo: no data for {symbol} ({err})")
    r = res[0]
    ts = r.get("timestamp") or []
    q = r["indicators"]["quote"][0]
    adj = (r["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        ratio = (adj[i] / c) if adj and adj[i] else 1.0
        bars.append({
            "date": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": (q["open"][i] or c) * ratio,
            "high": (q["high"][i] or c) * ratio,
            "low": (q["low"][i] or c) * ratio,
            "close": c * ratio,
            "volume": q["volume"][i] or 0,
        })
    return bars


def _stooq(symbol: str, years: int) -> list[dict]:
    s = symbol.lower()
    if "." not in s and "^" not in s:
        s += ".us"
    raw = _get(f"https://stooq.com/q/d/l/?s={urllib.parse.quote(s)}&i=d").decode()
    rows = list(csv.DictReader(io.StringIO(raw)))
    if not rows or "Close" not in rows[0]:
        raise DataError(f"stooq: no data for {symbol}")
    bars = [{
        "date": r["Date"], "open": float(r["Open"]), "high": float(r["High"]),
        "low": float(r["Low"]), "close": float(r["Close"]),
        "volume": float(r.get("Volume") or 0),
    } for r in rows if r.get("Close") not in (None, "", "null")]
    return bars[-(years * 252 + 5):]


def fetch_history(symbol: str, years: int = 2) -> list[dict]:
    """Daily bars (split/dividend adjusted when available), oldest first."""
    errors = []
    for src in (_yahoo, _stooq):
        try:
            bars = src(symbol, years)
            if len(bars) >= 30:
                for b in bars:
                    b["source"] = src.__name__.strip("_")
                return bars
            errors.append(f"{src.__name__}: only {len(bars)} bars")
        except Exception as exc:  # noqa: BLE001 - fall through to next source
            errors.append(str(exc))
    raise DataError(f"{symbol}: all sources failed -> " + " | ".join(errors))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("symbol")
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--csv", help="write full history to this CSV path")
    args = ap.parse_args()
    try:
        bars = fetch_history(args.symbol.upper(), args.years)
    except DataError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close", "volume", "source"])
            w.writeheader()
            w.writerows(bars)
    last, prev = bars[-1], bars[-2]
    print(json.dumps({
        "symbol": args.symbol.upper(),
        "as_of": last["date"],
        "close": round(last["close"], 4),
        "change_pct": round((last["close"] / prev["close"] - 1) * 100, 2),
        "bars": len(bars),
        "first_date": bars[0]["date"],
        "source": last["source"],
        "csv": args.csv,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
