"""Real option quotes: parsers for CBOE (free, delayed) and Schwab chains, and contract selection."""
from __future__ import annotations

import re
from datetime import date, timedelta

OCC = re.compile(r"^([A-Z.\-]{1,6})\s*(\d{6})([CP])(\d{8})$")


def parse_occ(sym: str):
    m = OCC.match((sym or "").replace(" ", "").upper().replace("-", "")) if sym else None
    if not m:
        m = OCC.match((sym or "").upper())
    if not m:
        return None
    root, ymd, cp, k = m.groups()
    return root, date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:])), "call" if cp == "C" else "put", int(k) / 1000.0


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_cboe(raw: dict) -> tuple[float | None, list[dict]]:
    """CBOE delayed-quotes JSON -> (underlying price, contracts)."""
    d = raw.get("data") or {}
    out = []
    for o in d.get("options") or []:
        p = parse_occ(o.get("option", ""))
        if not p:
            continue
        _, exp, cp, k = p
        bid, ask = _f(o.get("bid")), _f(o.get("ask"))
        out.append({"contract": f"{p[0]}{exp:%y%m%d}{'C' if cp == 'call' else 'P'}{int(round(k * 1000)):08d}", "cp": cp, "strike": k, "expiry": exp.isoformat(),
                    "bid": bid, "ask": ask, "last": _f(o.get("last_trade_price")), "iv": _f(o.get("iv")), "delta": _f(o.get("delta")),
                    "volume": _f(o.get("volume")), "oi": _f(o.get("open_interest"))})
    return _f(d.get("current_price")), out


def parse_schwab_chain(raw: dict) -> tuple[float | None, list[dict]]:
    """Schwab /marketdata/v1/chains JSON -> (underlying price, contracts)."""
    out = []
    for key in ("callExpDateMap", "putExpDateMap"):
        for _exp, strikes in (raw.get(key) or {}).items():
            for _k, lst in strikes.items():
                for o in lst:
                    p = parse_occ(o.get("symbol", ""))
                    if not p:
                        continue
                    _, exp, cp, k = p
                    iv = _f(o.get("volatility"))
                    out.append({"contract": f"{p[0]}{exp:%y%m%d}{'C' if cp == 'call' else 'P'}{int(round(k * 1000)):08d}", "cp": cp, "strike": k, "expiry": exp.isoformat(),
                                "bid": _f(o.get("bid")), "ask": _f(o.get("ask")), "last": _f(o.get("last")), "iv": (iv / 100.0 if iv and iv > 3 else iv),
                                "delta": _f(o.get("delta")), "volume": _f(o.get("totalVolume")), "oi": _f(o.get("openInterest"))})
    return _f(raw.get("underlyingPrice")), out


def usable(c, max_spread=0.20):
    b, a = c.get("bid"), c.get("ask")
    if not b or not a or b <= 0 or a <= 0 or a < b:
        return False
    return (a - b) / ((a + b) / 2) <= max_spread


def pick_contract(chain, cp, spot, today: date, min_days=28, otm_pct=2.0):
    """Nearest expiry at least `min_days` out, strike nearest ~2% out of the money, with a tradable (tight, two-sided) quote."""
    cands = [c for c in chain if c["cp"] == cp and (date.fromisoformat(c["expiry"]) - today).days >= min_days]
    if not cands:
        return None
    exp = min({c["expiry"] for c in cands})
    # prefer a standard Friday expiry close to the target; the nearest one is fine
    target = spot * (1 + otm_pct / 100) if cp == "call" else spot * (1 - otm_pct / 100)
    same = sorted((c for c in cands if c["expiry"] == exp), key=lambda c: abs(c["strike"] - target))
    for c in same[:4]:
        if usable(c) and (c.get("oi") or 0) >= 10:
            return c
    return None


def find_contract(chain, contract):
    for c in chain or []:
        if c["contract"] == contract:
            return c
    return None
