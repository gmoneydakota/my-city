#!/usr/bin/env python3
"""Daily market signals for the watchlist. Pure Python, zero Claude usage.

Runs on GitHub's servers after the US close (see .github/workflows/market-signals.yml)
and writes:
    outputs/signals/latest.json      <- the city's Market tab + quant billboard read this
    outputs/signals/report.md        <- human-readable version
    outputs/signals/history/DATE.json

Every signal comes with its reasons and an honest backtest of the same rule on that
symbol's own history, so you can see how often it actually worked.

    python3 scripts/signals.py            # real data
    python3 scripts/signals.py --demo     # synthetic prices, clearly labelled DEMO
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_data import DataError, fetch_history  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "signals"
FWD = 20  # trading days used to judge whether a past signal worked

DISCLAIMER = (
    "Educational signals from simple technical rules, not financial advice. "
    "Past behaviour of a rule does not guarantee future results. Do your own research."
)


# ---------- indicators (each returns a list aligned with closes, None until warm) ----------

def sma(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(xs, n):
    out, k, e = [None] * len(xs), 2 / (n + 1), None
    for i, x in enumerate(xs):
        e = x if e is None else x * k + e * (1 - k)
        out[i] = e if i >= n - 1 else None
    return out


def rsi(xs, n=14):
    out = [None] * len(xs)
    gain = loss = 0.0
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        g, l = max(d, 0), max(-d, 0)
        if i <= n:
            gain += g / n
            loss += l / n
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + l) / n
        if i >= n:
            out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def atr(bars, n=14):
    out, a = [None] * len(bars), None
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        a = tr if a is None else (a * (n - 1) + tr) / n
        if i >= n:
            out[i] = a
    return out


def macd_hist(xs):
    f, s = ema(xs, 12), ema(xs, 26)
    line = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
    valid = [v for v in line if v is not None]
    sig_v = ema(valid, 9)
    sig = [None] * (len(line) - len(valid)) + sig_v
    return [a - b if a is not None and b is not None else None for a, b in zip(line, sig)]


# ---------- the rule ----------

def score_at(i, c, s50, s200, r, mh, bench_ret63, own_ret63):
    """Score day i from -6..+7 and explain why. Returns (score, reasons) or (None, [])."""
    if None in (s50[i], s200[i], r[i], mh[i], mh[i - 1]) or i < 63:
        return None, []
    sc, why = 0, []
    p = c[i]
    if p > s200[i]:
        sc += 1; why.append("price above 200-day average (long-term uptrend)")
    else:
        sc -= 1; why.append("price below 200-day average (long-term downtrend)")
    if s50[i] > s200[i]:
        sc += 1; why.append("50-day above 200-day (golden-cross regime)")
    else:
        sc -= 1; why.append("50-day below 200-day (death-cross regime)")
    if own_ret63 is not None:
        if own_ret63 > 0:
            sc += 1; why.append(f"up {own_ret63*100:.1f}% over 3 months")
        if bench_ret63 is not None and own_ret63 > bench_ret63:
            sc += 1; why.append("outperforming the benchmark over 3 months")
    if mh[i] > 0 and mh[i] > mh[i - 1]:
        sc += 1; why.append("MACD momentum positive and rising")
    elif mh[i] < 0 and mh[i] < mh[i - 1]:
        sc -= 1; why.append("MACD momentum negative and falling")
    if r[i] < 32:
        sc += 1 if p > s200[i] else 0
        why.append(f"RSI {r[i]:.0f}: oversold" + (" inside an uptrend (dip-buy setup)" if p > s200[i] else ""))
    elif r[i] > 75:
        sc -= 1; why.append(f"RSI {r[i]:.0f}: overbought, chasing risk is high")
    if p > s200[i] and abs(p / s50[i] - 1) < 0.03 and r[i] < 55:
        sc += 2; why.append("pulled back to the 50-day in an uptrend (classic entry zone)")
    return sc, why


def label(sc):
    if sc >= 5:
        return "BUY ZONE"
    if sc >= 3:
        return "WATCH / ACCUMULATE"
    if sc >= 0:
        return "HOLD / NEUTRAL"
    return "AVOID"


def analyse(sym, bars, bench_closes_by_date):
    c = [b["close"] for b in bars]
    dates = [b["date"] for b in bars]
    s50, s200, r, mh, a = sma(c, 50), sma(c, 200), rsi(c), macd_hist(c), atr(bars)

    def ret63(i, closes):
        return closes[i] / closes[i - 63] - 1 if i >= 63 else None

    bench = [bench_closes_by_date.get(d) for d in dates]

    def bench_ret63(i):
        if i < 63 or bench[i] is None or bench[i - 63] is None:
            return None
        return bench[i] / bench[i - 63] - 1

    scores = [None] * len(c)
    for i in range(1, len(c)):
        scores[i], _ = score_at(i, c, s50, s200, r, mh, bench_ret63(i), ret63(i, c))

    # honest backtest: forward 20-day return after BUY-ZONE days vs all days
    fwd_sig, fwd_all = [], []
    for i in range(len(c) - FWD):
        if scores[i] is None:
            continue
        f = c[i + FWD] / c[i] - 1
        fwd_all.append(f)
        if scores[i] >= 5:
            fwd_sig.append(f)
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731

    i = len(c) - 1
    sc, why = score_at(i, c, s50, s200, r, mh, bench_ret63(i), ret63(i, c))
    if sc is None:
        return {"symbol": sym, "error": "not enough history (need ~200 trading days)"}
    hi52, lo52 = max(c[-252:]), min(c[-252:])
    return {
        "symbol": sym,
        "as_of": dates[i],
        "price": round(c[i], 2),
        "change_pct": round((c[i] / c[i - 1] - 1) * 100, 2),
        "score": sc,
        "signal": label(sc),
        "reasons": why,
        "rsi": round(r[i], 1),
        "sma50": round(s50[i], 2),
        "sma200": round(s200[i], 2),
        "pct_from_52w_high": round((c[i] / hi52 - 1) * 100, 1),
        "pct_above_52w_low": round((c[i] / lo52 - 1) * 100, 1),
        "suggested_stop": round(c[i] - 2 * a[i], 2) if a[i] else None,
        "score_history": [s for s in scores[-60:] if s is not None],
        "backtest": {
            "rule": f"score >= 5, judged {FWD} trading days later",
            "signal_days": len(fwd_sig),
            "avg_fwd_return_pct_when_signal": round(mean(fwd_sig) * 100, 2) if fwd_sig else None,
            "avg_fwd_return_pct_any_day": round(mean(fwd_all) * 100, 2) if fwd_all else None,
            "win_rate_pct_when_signal": round(100 * sum(f > 0 for f in fwd_sig) / len(fwd_sig), 1) if fwd_sig else None,
        },
        "source": bars[-1].get("source", "?"),
    }


def demo_bars(sym, n=600):
    rnd = random.Random(sym)
    p, drift, vol = rnd.uniform(40, 400), rnd.uniform(-0.0004, 0.0012), rnd.uniform(0.012, 0.03)
    start = datetime.now(timezone.utc) - timedelta(days=int(n * 1.45))
    bars, d = [], start
    while len(bars) < n:
        d += timedelta(days=1)
        if d.weekday() >= 5:
            continue
        o = p
        p *= math.exp(rnd.gauss(drift, vol))
        bars.append({"date": d.strftime("%Y-%m-%d"), "open": o, "high": max(o, p) * 1.006,
                     "low": min(o, p) * 0.994, "close": p, "volume": 1e6, "source": "demo"})
    return bars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="synthetic prices (for testing only)")
    ap.add_argument("--watchlist", default=str(ROOT / "watchlist.json"))
    args = ap.parse_args()

    cfg = json.loads(Path(args.watchlist).read_text())
    symbols = [s.upper() for s in cfg["symbols"]]
    bench_sym = cfg.get("benchmark", "SPY").upper()
    get = demo_bars if args.demo else (lambda s: fetch_history(s, years=3))

    try:
        bench = {b["date"]: b["close"] for b in get(bench_sym)}
    except DataError as exc:
        print(f"warning: benchmark failed: {exc}", file=sys.stderr)
        bench = {}

    results = []
    for sym in symbols:
        try:
            results.append(analyse(sym, get(sym), bench))
        except Exception as exc:  # keep going; one bad ticker shouldn't sink the run
            results.append({"symbol": sym, "error": str(exc)[:300]})
        print(f"{sym:8s} {results[-1].get('signal', 'ERROR: ' + results[-1].get('error', ''))}")

    ok = [r for r in results if "error" not in r]
    if not ok:
        print("no symbols succeeded; not overwriting previous signals", file=sys.stderr)
        return 1
    ok.sort(key=lambda r: -r["score"])
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": "DEMO (synthetic prices)" if args.demo else "Yahoo Finance / Stooq daily bars",
        "demo": bool(args.demo),
        "benchmark": bench_sym,
        "disclaimer": DISCLAIMER,
        "symbols": ok + [r for r in results if "error" in r],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "history").mkdir(exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(payload, indent=2))
    (OUT / "history" / f"{ok[0]['as_of']}.json").write_text(json.dumps(payload))

    lines = [f"# Market signals - {ok[0]['as_of']}", "", f"_{DISCLAIMER}_", "",
             "| Symbol | Price | Day | Signal | Score | RSI | Stop | Past BUY-ZONE hit rate |",
             "|---|---|---|---|---|---|---|---|"]
    for r in ok:
        bt = r["backtest"]
        hit = f"{bt['win_rate_pct_when_signal']}% of {bt['signal_days']}" if bt["signal_days"] else "no past signals"
        lines.append(f"| {r['symbol']} | {r['price']} | {r['change_pct']:+.2f}% | **{r['signal']}** | "
                     f"{r['score']} | {r['rsi']} | {r['suggested_stop']} | {hit} |")
    lines += ["", "## Why"]
    for r in ok:
        lines += [f"### {r['symbol']} - {r['signal']}"] + [f"- {w}" for w in r["reasons"]] + [""]
    (OUT / "report.md").write_text("\n".join(lines))
    print(f"wrote {OUT/'latest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
