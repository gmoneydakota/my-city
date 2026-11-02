"""Indicators, per-symbol features and Black-Scholes pricing. No third-party packages."""
from __future__ import annotations

import math

# ---------------------------------------------------------------- indicators

def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def rsi(closes, n=14):
    """Wilder RSI of the last bar."""
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def atr(bars, n=14):
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def hist_vol(closes, n=20):
    """Annualised close-to-close volatility."""
    if len(closes) < n + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]
    return stdev(rets) * math.sqrt(252) if len(rets) > 2 else None


def pct(a, b):
    return (a / b - 1) * 100 if b else 0.0


def features(bars, spy_ret60=0.0):
    """Daily features for one symbol, from COMPLETED sessions only (oldest first)."""
    if len(bars) < 60:
        return None
    c = [b["close"] for b in bars]
    v = [b.get("volume") or 0 for b in bars]
    last = c[-1]
    s20, s50 = sma(c, 20), sma(c, 50)
    s200 = sma(c, 200) if len(c) >= 200 else None
    s10, s5 = sma(c, 10), sma(c, 5)
    a = atr(bars, 14) or 0.0
    w20 = c[-20:]
    m20, sd20 = sum(w20) / 20, stdev(w20)
    ret = lambda n: pct(last, c[-n - 1]) if len(c) > n else None
    r60 = ret(60)
    hv20, hv60 = hist_vol(c, 20), hist_vol(c, 60)
    avgvol = sum(v[-20:]) / 20
    return {
        "close": round(last, 4), "date": bars[-1]["date"],
        "sma5": round(s5, 4), "sma10": round(s10, 4), "sma20": round(s20, 4), "sma50": round(s50, 4),
        "sma200": round(s200, 4) if s200 else None,
        "rsi2": round(rsi(c, 2) or 50, 2), "rsi14": round(rsi(c, 14) or 50, 2),
        "atr": round(a, 4), "atr_pct": round(a / last * 100, 3) if last else 0,
        "hh20": round(max(b["high"] for b in bars[-20:]), 4), "ll20": round(min(b["low"] for b in bars[-20:]), 4),
        "hh252": round(max(b["high"] for b in bars[-252:]), 4),
        "bb_up": round(m20 + 2 * sd20, 4), "bb_lo": round(m20 - 2 * sd20, 4),
        "avgvol": round(avgvol), "dollar_vol": round(avgvol * last),
        "r5": round(ret(5), 2), "r20": round(ret(20), 2), "r60": round(r60, 2) if r60 is not None else None,
        "rs60": round((r60 - spy_ret60), 2) if r60 is not None else None,
        "hv20": round(hv20, 4) if hv20 else None, "hv60": round(hv60, 4) if hv60 else None,
        "prev_close": round(c[-1], 4), "prev_chg": round(pct(c[-1], c[-2]), 2),
    }


# ---------------------------------------------------------------- options (Black-Scholes)

def _cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(S, K, T, r, sigma, kind):
    """European option price per share. kind is 'call' or 'put'."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "call":
        return S * _cdf(d1) - K * math.exp(-r * T) * _cdf(d2)
    return K * math.exp(-r * T) * _cdf(-d2) - S * _cdf(-d1)


def bs_delta(S, K, T, r, sigma, kind):
    if T <= 0 or sigma <= 0:
        return (1.0 if S > K else 0.0) if kind == "call" else (-1.0 if S < K else 0.0)
    d1 = (math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * math.sqrt(T))
    return _cdf(d1) if kind == "call" else _cdf(d1) - 1


def strike_step(price):
    return 0.5 if price < 25 else 1.0 if price < 100 else 2.5 if price < 250 else 5.0 if price < 1000 else 10.0


def pick_strike(price, kind, otm_pct=2.0):
    step = strike_step(price)
    target = price * (1 + otm_pct / 100) if kind == "call" else price * (1 - otm_pct / 100)
    return round(round(target / step) * step, 2)


def est_iv(hv20, hv60, vix):
    """Rough implied-vol estimate used to price paper options (no live chain needed)."""
    base = [x for x in (hv20, hv60) if x]
    b = sum(base) / len(base) if base else 0.30
    return max(0.18, min(1.6, b * 1.12 * (1 + max(0.0, ((vix or 18) - 18) / 100))))
