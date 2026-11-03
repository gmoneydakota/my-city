"""Paper accounts: fills, marking, leaderboards and the real-money scorecard."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

START_CASH = 100_000.0
STOCK_SLIP = 0.0003          # 3 bps each way
OPT_COMMISSION = 0.65        # per contract, each way
OPT_HALF_SPREAD = 0.025      # pay 2.5% over / get 2.5% under the model mid price


def new_account(tid: str) -> dict:
    return {"id": tid, "cash": START_CASH, "start_cash": START_CASH, "positions": [], "trades": [], "orders": [],
            "daily_close": {}, "equity_history": [], "next_id": 1, "cooldown": {}, "last_run": {}}


def position_value(p: dict) -> float:
    mult = 100 if p["kind"] != "stock" else 1
    return p["qty"] * p.get("mark", p["entry"]) * mult


def equity(acct: dict) -> float:
    return acct["cash"] + sum(position_value(p) for p in acct["positions"])


def open_position(acct: dict, *, kind, symbol, qty, price, ts, horizon, stop, target, thesis, tags=None,
                  option=None, max_days=5, underlying=None, fill=None, src="model") -> dict | None:
    """Buy `qty` shares (or contracts). `price` is the market mid; slippage/spread is added here,
    unless a real `fill` (e.g. the quoted ask) is given."""
    if qty <= 0:
        return None
    if kind == "stock":
        fill, fee, mult = (fill if fill is not None else price * (1 + STOCK_SLIP)), 0.0, 1
    else:
        fill, fee, mult = (fill if fill is not None else price * (1 + OPT_HALF_SPREAD)), OPT_COMMISSION * qty, 100
    cost = qty * fill * mult + fee
    if cost > acct["cash"] + 1e-9:
        return None
    acct["cash"] -= cost
    pos = {"id": acct["next_id"], "kind": kind, "symbol": symbol, "qty": qty, "entry": round(fill, 4), "mark": round(fill, 4),
           "entry_ts": ts, "horizon": horizon, "stop": stop, "target": target, "thesis": thesis, "tags": tags or [],
           "max_days": max_days, "fees": fee, "underlying_entry": underlying, "high_water": fill}
    if option:
        pos["option"] = option
    acct["next_id"] += 1
    pos["track"] = [[ts, round(fill, 4), round(underlying, 4) if underlying else None]]
    acct["positions"].append(pos)
    _order(acct, {"ts": ts, "side": "BUY", "id": pos["id"], "symbol": symbol, "kind": kind, "qty": qty, "ref": round(price, 4), "fill": round(fill, 4),
                  "fees": round(fee, 2), "value": round(qty * fill * mult, 2), "why": (thesis[:230] + "…") if len(thesis) > 230 else thesis, "src": src, "option": option,
                  "slip": round((fill - price) * qty * mult, 2), "cash_after": round(acct["cash"], 2)})
    return pos


def _order(acct, rec):
    acct.setdefault("orders", []).append(rec)
    if len(acct["orders"]) > 300:
        acct["orders"] = acct["orders"][-300:]


def close_position(acct: dict, pos: dict, price: float, ts: str, reason: str, fill=None, src="model") -> dict:
    """Sell a position at market `price` (before slippage/spread), or at a real `fill` (e.g. the quoted bid)."""
    if pos["kind"] == "stock":
        fill, fee, mult = (fill if fill is not None else price * (1 - STOCK_SLIP)), 0.0, 1
    else:
        fill, fee, mult = (fill if fill is not None else max(price * (1 - OPT_HALF_SPREAD), 0.0)), OPT_COMMISSION * pos["qty"], 100
    proceeds = pos["qty"] * fill * mult - fee
    cost = pos["qty"] * pos["entry"] * mult + pos["fees"]
    acct["cash"] += proceeds
    acct["positions"] = [p for p in acct["positions"] if p["id"] != pos["id"]]
    pnl = proceeds - cost
    tr = {"id": pos["id"], "symbol": pos["symbol"], "kind": pos["kind"], "horizon": pos["horizon"], "qty": pos["qty"],
          "entry": pos["entry"], "exit": round(fill, 4), "entry_ts": pos["entry_ts"], "exit_ts": ts, "pnl": round(pnl, 2),
          "ret_pct": round(pnl / cost * 100, 2) if cost else 0.0, "reason": reason, "thesis": pos["thesis"],
          "tags": pos.get("tags", []), "option": pos.get("option"), "stop": pos.get("stop"), "target": pos.get("target"),
          "track": _thin(pos.get("track", []), 24)}
    _order(acct, {"ts": ts, "side": "SELL", "id": pos["id"], "symbol": pos["symbol"], "kind": pos["kind"], "qty": pos["qty"], "ref": round(price, 4),
                  "fill": round(fill, 4), "fees": round(fee, 2), "value": round(pos["qty"] * fill * mult, 2), "why": reason, "src": src,
                  "option": pos.get("option"), "pnl": round(pnl, 2), "ret_pct": tr["ret_pct"], "cash_after": round(acct["cash"], 2)})
    acct["trades"].append(tr)
    if len(acct["trades"]) > 500:
        acct["trades"] = acct["trades"][-500:]
    if pnl < 0:
        acct["cooldown"][pos["symbol"]] = ts[:10]
    return tr


def _thin(xs, n):
    if len(xs) <= n:
        return xs
    step = (len(xs) - 1) / (n - 1)
    return [xs[round(i * step)] for i in range(n)]


def snapshot(acct: dict, ts: str, keep: int = 420):
    acct["equity_history"].append([ts, round(equity(acct), 2)])
    if len(acct["equity_history"]) > keep:
        acct["equity_history"] = acct["equity_history"][-keep:]


# ---------------------------------------------------------------- leaderboard

def _baseline(daily_close: dict, before: date, start_cash: float) -> float:
    ds = [d for d in daily_close if date.fromisoformat(d) < before]
    return daily_close[max(ds)] if ds else start_cash


def window_returns(acct: dict, today: date) -> dict:
    """P&L for today / this week / this month / since start, vs the last close before each period."""
    eq = equity(acct)
    week_start = today - timedelta(days=today.weekday())
    out = {}
    for name, since in (("day", today), ("week", week_start), ("month", today.replace(day=1))):
        base = _baseline(acct["daily_close"], since, acct["start_cash"])
        out[name] = {"pnl": round(eq - base, 2), "pct": round((eq / base - 1) * 100, 3) if base else 0.0, "base": round(base, 2)}
    out["all"] = {"pnl": round(eq - acct["start_cash"], 2), "pct": round((eq / acct["start_cash"] - 1) * 100, 3), "base": acct["start_cash"]}
    return out


def champions(accts: dict, limit: int = 12) -> dict:
    """Winner of every finished day / week / month, from the end-of-day equity records."""
    days = sorted({d for a in accts.values() for d in a["daily_close"]})
    res = {"day": [], "week": [], "month": []}
    if not days:
        return res

    def pick(label, start_base_date, end_date):
        row = {}
        for tid, a in accts.items():
            if end_date not in a["daily_close"]:
                continue
            base = _baseline(a["daily_close"], start_base_date, a["start_cash"])
            row[tid] = a["daily_close"][end_date] - base
        if len(row) == len(accts):
            w = max(row, key=row.get)
            return {"label": label, "winner": w, "pnl": {k: round(v, 2) for k, v in row.items()}}
    # day
    for d in days:
        r = pick(d, date.fromisoformat(d), d)
        if r:
            res["day"].append(r)
    # week / month: last trading day of each period
    for kind, keyf, startf in (("week", lambda x: x.isocalendar()[:2], lambda x: x - timedelta(days=x.weekday())),
                               ("month", lambda x: (x.year, x.month), lambda x: x.replace(day=1))):
        groups = {}
        for d in days:
            groups.setdefault(keyf(date.fromisoformat(d)), []).append(d)
        for k in sorted(groups):
            last = groups[k][-1]
            r = pick(f"{groups[k][0]} → {last}" if kind == "week" else last[:7], startf(date.fromisoformat(last)), last)
            if r:
                res[kind].append(r)
    for k in res:
        res[k] = res[k][-limit:]
    return res


# ---------------------------------------------------------------- scorecard

CRITERIA = [
    ("days", "At least 60 trading days of record", 60),
    ("trades", "At least 40 closed trades", 40),
    ("beats_spy", "Beat the S&P 500 (SPY) over the same period", None),
    ("sharpe", "Sharpe ratio of 1.0 or better", 1.0),
    ("max_dd", "Worst peak-to-trough drop no worse than 15%", 15.0),
    ("profit_factor", "Profit factor (gross wins / gross losses) of 1.3 or better", 1.3),
    ("months", "Profitable in at least 2 of the last 3 months", 2),
    ("concentration", "No single trade made more than 40% of total profit", 40.0),
]


def scorecard(acct: dict, bench: dict) -> dict:
    dc = acct["daily_close"]
    days = sorted(dc)
    vals = [dc[d] for d in days]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    if vals:
        rets_all = [vals[0] / acct["start_cash"] - 1] + rets
    else:
        rets_all = []
    mean = sum(rets_all) / len(rets_all) if rets_all else 0
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets_all) / (len(rets_all) - 1)) if len(rets_all) > 2 else 0
    sharpe = (mean / sd * math.sqrt(252)) if sd > 0 else 0.0
    peak, mdd = acct["start_cash"], 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
    tr = acct["trades"]
    wins = [t["pnl"] for t in tr if t["pnl"] > 0]
    losses = [-t["pnl"] for t in tr if t["pnl"] <= 0]
    gw, gl = sum(wins), sum(losses)
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
    total_profit = sum(t["pnl"] for t in tr)
    best = max((t["pnl"] for t in tr), default=0)
    conc = (best / total_profit * 100) if total_profit > 0 else (100.0 if tr else 0.0)
    ret_pct = ((vals[-1] / acct["start_cash"] - 1) * 100) if vals else 0.0
    spy_ret = None
    bd = sorted(bench)
    if days and bd:
        first = next((d for d in bd if d >= days[0]), None)
        last = bench.get(days[-1]) or bench[bd[-1]]
        before = [d for d in bd if d < days[0]]
        b0 = bench[before[-1]] if before else (bench[first] if first else None)
        if b0:
            spy_ret = (last / b0 - 1) * 100
    months = {}
    prev = acct["start_cash"]
    for d in days:
        months.setdefault(d[:7], []).append(dc[d])
    mret = []
    for m in sorted(months):
        mret.append(months[m][-1] - prev)
        prev = months[m][-1]
    last3 = mret[-3:]
    checks = {
        "days": (len(days), len(days) >= 60), "trades": (len(tr), len(tr) >= 40),
        "beats_spy": (None if spy_ret is None else round(ret_pct - spy_ret, 2), spy_ret is not None and ret_pct > spy_ret),
        "sharpe": (round(sharpe, 2), sharpe >= 1.0), "max_dd": (round(mdd, 2), mdd <= 15.0 and len(days) > 0),
        "profit_factor": (None if pf == float("inf") else round(pf, 2), pf >= 1.3),
        "months": (sum(1 for m in last3 if m > 0), sum(1 for m in last3 if m > 0) >= 2 and len(last3) >= 2),
        "concentration": (round(conc, 1), 0 < conc <= 40.0),
    }
    passed = sum(1 for v in checks.values() if v[1])
    return {"checks": {k: {"value": v[0], "pass": bool(v[1]), "label": lbl} for (k, lbl, _), v in zip(CRITERIA, (checks[c[0]] for c in CRITERIA))},
            "passed": passed, "total": len(CRITERIA), "return_pct": round(ret_pct, 2),
            "spy_return_pct": None if spy_ret is None else round(spy_ret, 2), "win_rate": round(len(wins) / len(tr) * 100, 1) if tr else None,
            "avg_win": round(gw / len(wins), 2) if wins else 0, "avg_loss": round(-gl / len(losses), 2) if losses else 0,
            "trades": len(tr), "days": len(days), "eligible": passed == len(CRITERIA)}
