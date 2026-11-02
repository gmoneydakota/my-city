"""The three competing traders. Each one scans the whole market and proposes trades with a written thesis.

All three start with $100,000 of paper money and trade stocks plus long calls/puts.
They differ in what they believe moves prices:

  Momentum Mo ... trend + relative strength: buys breakouts in market leaders.
  Reversion Rae . mean reversion: buys panic in healthy stocks, fades blow-off rallies with puts.
  Catalyst Cal .. news + volume + earnings + macro regime: trades events and sentiment extremes.
"""
from __future__ import annotations

from .sources import sentiment

# Index / sector ETFs are used as market context, not traded as "stocks" by the single-stock rules.
ETFS = set("SPY QQQ IWM DIA XLF XLE XLK XLV XLY XLP XLI XLU XLB XLRE XLC SMH GLD TLT UUP".split())

MIN_PRICE = 10.0
MIN_DOLLAR_VOL = 25e6


def liquid(f, q):
    return f and q and q["price"] >= MIN_PRICE and f["dollar_vol"] >= MIN_DOLLAR_VOL and f["atr"] > 0


def fmt(x):
    return f"${x:,.2f}"


class Trader:
    id = ""
    name = ""
    emoji = ""
    color = "#fff"
    style = ""
    bio = ""
    rules: list[str] = []
    max_positions = 5
    max_new_per_run = 2
    first_entry_min = 60       # minutes after the open before this trader may enter
    last_entry_min = 300       # no new entries after 2:30pm ET
    loss_halt_pct = -3.0       # stop opening trades if down this much today

    def profile(self):
        return {"id": self.id, "name": self.name, "emoji": self.emoji, "color": self.color, "style": self.style,
                "bio": self.bio, "rules": self.rules}

    def scan(self, ctx, acct) -> list[dict]:  # pragma: no cover - overridden
        return []


class MomentumMo(Trader):
    id, name, emoji, color = "mo", "Momentum Mo", "🚀", "#3ddc84"
    style = "Trend & relative strength"
    bio = "Rides leaders. Buys stocks breaking out to new highs on heavy volume while the whole trend is up; uses calls when everything lines up."
    rules = [
        "Only stocks in a clean uptrend: price > 50-day average > 200-day average",
        "Must rank in the top 20% of the market for 60-day strength versus SPY",
        "Entry: trading at/above its 20-day high, above today's VWAP, volume running ≥1.2× normal",
        "Skips anything stretched more than 4 ATR above its 20-day average (no chasing)",
        "Stock: stop 1.5×ATR below, target 3×ATR above, trailing stop once it's working, held up to 8 days",
        "Calls (2.5% of the account, 4+ weeks out): only when the setup is exceptional and the market regime is risk-on",
        "Halves its size when the market regime is risk-off",
    ]

    def scan(self, ctx, acct):
        out = []
        for s, f in ctx.feat.items():
            q = ctx.quote.get(s)
            if s in ETFS or not liquid(f, q) or not f.get("sma200") or f.get("rs_rank") is None:
                continue
            p = q["price"]
            if not (p > f["sma50"] > f["sma200"]) or f["rs_rank"] < 80:
                continue
            if p < f["hh20"] * 0.995:
                continue
            if (p - f["sma20"]) / f["atr"] > 4:
                continue
            vp = q.get("vol_pace")
            if vp is not None and vp < 1.2:
                continue
            if q.get("vwap") and p < q["vwap"]:
                continue
            if q["chg_pct"] < 0.2:
                continue
            at_high = p >= f["hh20"]
            score = f["rs_rank"] / 10 + (3 if at_high else 1.5) + min(3.0, vp or 1.0) + min(2.0, q["chg_pct"] * 0.5)
            stop, target = p - 1.5 * f["atr"], p + 3 * f["atr"]
            thesis = (f"Breakout: {fmt(p)} is {'at a new' if at_high else 'right at the'} 20-day high ({fmt(f['hh20'])}), {q['chg_pct']:+.1f}% today"
                      f"{f' on {vp:.1f}× normal volume' if vp else ''}, above VWAP ({fmt(q['vwap'])}). "
                      f"60-day strength ranks {f['rs_rank']:.0f}/100 vs the market and the trend is intact (50d > 200d). "
                      f"Risk: stop {fmt(stop)} (1.5×ATR), target {fmt(target)}.")
            tags = ["breakout", "trend"]
            if score >= 14 and ctx.regime == "risk-on" and (f.get("hv20") or 1) < 0.7:
                out.append({"symbol": s, "kind": "call", "horizon": "swing", "score": score + 1, "thesis": thesis + " Setup is exceptional and the market is risk-on, so it buys a call for leverage.",
                            "premium_frac": 0.025, "stop_pct": -40, "target_pct": 70, "max_days": 6, "tags": tags + ["options"]})
            else:
                out.append({"symbol": s, "kind": "stock", "horizon": "swing", "score": score, "thesis": thesis, "stop": stop, "target": target,
                            "risk_frac": 0.0075 * (0.5 if ctx.regime == "risk-off" else 1.0), "max_days": 8, "tags": tags})
        return sorted(out, key=lambda x: -x["score"])


class ReversionRae(Trader):
    id, name, emoji, color = "rae", "Reversion Rae", "🧲", "#4fd1ff"
    style = "Mean reversion & fades"
    bio = "Buys fear in healthy stocks and sells greed. Looks for sharp, stretched moves that snap back to the average; buys puts on blow-off rallies in weak stocks."
    rules = [
        "Dip buys: stock still above its 200-day average, 2-day RSI under 12 or below the lower Bollinger band, down ≥1% today but bouncing off the low",
        "Stop 2×ATR below; target the 10-day average (at least +1.2×ATR); time stop 5 days",
        "Gap-fill day trades: gaps down ≥2% in an uptrend that start to reclaim the open; flat by the close",
        "Puts (2% of the account): 2-day RSI above 95, above the upper band, up ≥8% in 5 days and below its 200-day (a bear-market rally)",
        "Won't buy a dip in a stock that closed below its 200-day average",
        "Sits out symbols it just lost money on for two days",
    ]

    def scan(self, ctx, acct):
        out = []
        for s, f in ctx.feat.items():
            q = ctx.quote.get(s)
            if s in ETFS or not liquid(f, q):
                continue
            p = q["price"]
            up_long = bool(f.get("sma200")) and f["close"] > f["sma200"]
            # 1) gap-fill day trade
            if up_long and q["gap_pct"] <= -2.0 and p > q["open"] * 1.001 and (q.get("vol_pace") or 1.0) >= 1.0:
                stop = q["low"] * 0.998
                target = min(f["close"] * 0.995, p + 1.5 * f["atr"])
                if stop < p < target:
                    out.append({"symbol": s, "kind": "stock", "horizon": "day", "score": abs(q["gap_pct"]) * 1.4, "stop": stop, "target": target,
                                "risk_frac": 0.006, "max_days": 1, "tags": ["gap-fill", "day-trade"],
                                "thesis": f"Gap-fill day trade: gapped {q['gap_pct']:.1f}% below yesterday's close ({fmt(f['close'])}) and is now reclaiming its open ({fmt(q['open'])}) at {fmt(p)}. "
                                          f"Long-term trend is up, so it bets on the gap closing toward {fmt(target)}. Stop under the day low {fmt(stop)}; flat by the close."})
                    continue
            # 2) oversold dip in an uptrend
            if up_long and (f["rsi2"] < 12 or p < f["bb_lo"]) and q["chg_pct"] <= -1.0 and p > q["low"] * 1.002:
                score = (30 - f["rsi2"]) / 3 + abs(q["chg_pct"]) + (3 if p < f["bb_lo"] else 0) + (2 if f["rsi14"] < 35 else 0)
                stop = p - 2 * f["atr"]
                target = max(f["sma10"], p + 1.2 * f["atr"])
                out.append({"symbol": s, "kind": "stock", "horizon": "swing", "score": score, "stop": stop, "target": target, "risk_frac": 0.0075,
                            "max_days": 5, "tags": ["oversold", "dip-buy"],
                            "thesis": f"Dip buy: {s} is down {q['chg_pct']:.1f}% today to {fmt(p)} after 2-day RSI of {f['rsi2']:.0f}"
                                      f"{' and a close outside the lower Bollinger band' if p < f['bb_lo'] else ''}, but it is still above its 200-day ({fmt(f['sma200'])}) and off the day's low. "
                                      f"Expects a snap back toward the 10-day average ({fmt(target)}). Stop {fmt(stop)} (2×ATR)."})
                continue
            # 3) blow-off fade with a put
            if f["rsi2"] > 95 and p > f["bb_up"] and (f["r5"] or 0) >= 8 and f.get("sma200") and f["close"] < f["sma200"]:
                out.append({"symbol": s, "kind": "put", "horizon": "swing", "score": (f["r5"] or 0) + (f["rsi2"] - 90) / 2, "premium_frac": 0.02,
                            "stop_pct": -40, "target_pct": 55, "max_days": 4, "tags": ["blow-off", "fade", "options"],
                            "thesis": f"Fade: {s} is up {f['r5']:.0f}% in 5 days, 2-day RSI {f['rsi2']:.0f}, trading above its upper Bollinger band at {fmt(p)} while still under its 200-day ({fmt(f['sma200'])}). "
                                      f"That is a stretched bear-market rally, so it buys a put expecting a pullback."})
        return sorted(out, key=lambda x: -x["score"])


class CatalystCal(Trader):
    id, name, emoji, color = "cal", "Catalyst Cal", "📰", "#ffb547"
    style = "News, volume & macro regime"
    bio = "Trades events. Scans headlines, unusual volume, gaps and earnings reactions across the market, and makes contrarian bets at sentiment extremes."
    rules = [
        "Looks at stocks moving ≥1.5% on unusual volume, then reads their latest headlines (Google News + Yahoo Finance)",
        "Trades only when the headline tone and the price reaction agree (or an earnings reaction is large and on heavy volume)",
        "Positive: day-trade the stock (flat by the close) or a call if the score is very high and no earnings are near",
        "Negative: buys puts only (never shorts stock); skips options if earnings are today or tomorrow (volatility crush)",
        "Macro contrarian: small SPY calls in extreme fear (Fear & Greed ≤ 20 with VIX ≥ 28); small SPY puts in euphoria (≥ 85 with VIX ≤ 14)",
        "Cuts size 50% when the VIX is above 30",
    ]
    first_entry_min = 0

    def scan(self, ctx, acct):
        out = []
        size_mult = 0.5 if (ctx.macro.get("vix") or 0) > 30 else 1.0
        movers = []
        for s, f in ctx.feat.items():
            q = ctx.quote.get(s)
            if s in ETFS or not liquid(f, q):
                continue
            vp = q.get("vol_pace")
            big = abs(q["chg_pct"]) >= 1.5
            if big and (vp is None or vp >= 1.5 or s in ctx.earnings_today):
                movers.append((abs(q["chg_pct"]) * (vp or 1.5), s))
        movers = [s for _, s in sorted(movers, reverse=True)[:20]]
        headlines = ctx.news_for(movers) if movers else {}
        for s in movers:
            f, q = ctx.feat[s], ctx.quote[s]
            titles = [h["title"] for h in headlines.get(s, [])]
            tone = sentiment(titles)
            direction = 1 if q["chg_pct"] > 0 else -1
            earnings_move = s in ctx.earnings_today and abs(q["chg_pct"]) >= 3 and (q.get("vol_pace") or 2) >= 1.8
            agree = (tone * direction >= 0.12 and len(titles) >= 2) or earnings_move
            if not agree:
                continue
            vp = q.get("vol_pace") or 1.5
            score = abs(q["chg_pct"]) / max(f["atr_pct"], 0.5) * 1.5 + vp + abs(tone) * 4 + (2 if s in ctx.earnings_today else 0) + (1 if len(titles) >= 5 else 0)
            why = (f"{'Earnings reaction' if earnings_move else 'News-driven move'}: {s} {q['chg_pct']:+.1f}% at {fmt(q['price'])} on {vp:.1f}× normal volume; "
                   f"{len(titles)} recent headlines read {'positive' if tone > 0 else 'negative' if tone < 0 else 'neutral'} (tone {tone:+.2f}). "
                   f"Top headline: \"{titles[0][:110] if titles else 'earnings report'}\". ")
            earn_near = s in ctx.earnings_today or s in ctx.earnings_tomorrow
            if direction > 0:
                if score >= 9 and not earn_near and (f.get("hv20") or 1) < 0.8:
                    out.append({"symbol": s, "kind": "call", "horizon": "swing", "score": score, "premium_frac": 0.02 * size_mult, "stop_pct": -35,
                                "target_pct": 60, "max_days": 4, "tags": ["news", "options"], "thesis": why + "Score is high and no earnings are close, so it buys a call to ride continuation."})
                else:
                    p = q["price"]
                    stop = p - max(1.0 * f["atr"], p * 0.008)
                    target = p + 1.6 * (p - stop)
                    out.append({"symbol": s, "kind": "stock", "horizon": "day", "score": score, "stop": stop, "target": target, "risk_frac": 0.006 * size_mult,
                                "max_days": 1, "tags": ["news", "day-trade"], "thesis": why + f"Day trade for continuation: stop {fmt(stop)}, target {fmt(target)}, flat by the close."})
            elif score >= 7 and not earn_near:
                out.append({"symbol": s, "kind": "put", "horizon": "swing", "score": score, "premium_frac": 0.015 * size_mult, "stop_pct": -35,
                            "target_pct": 55, "max_days": 4, "tags": ["news", "options", "bearish"], "thesis": why + "Selling pressure confirmed by headlines, so it buys a put (it never shorts stock)."})
        # macro contrarian trades on SPY
        fng, vix = (ctx.macro.get("fng") or {}).get("score"), ctx.macro.get("vix")
        spy = ctx.quote.get("SPY")
        if fng is not None and vix and spy and "SPY" in ctx.feat:
            if fng <= 20 and vix >= 28:
                out.append({"symbol": "SPY", "kind": "call", "horizon": "swing", "score": 8 + (20 - fng) / 5, "premium_frac": 0.02, "stop_pct": -40, "target_pct": 70,
                            "max_days": 8, "tags": ["macro", "contrarian", "options"],
                            "thesis": f"Macro contrarian: CNN Fear & Greed is {fng:.0f} (extreme fear) with VIX at {vix:.1f}. Panic like this has often been near short-term lows, so it buys a small SPY call."})
            elif fng >= 85 and vix <= 14:
                out.append({"symbol": "SPY", "kind": "put", "horizon": "swing", "score": 8 + (fng - 85) / 5, "premium_frac": 0.015, "stop_pct": -40, "target_pct": 60,
                            "max_days": 8, "tags": ["macro", "contrarian", "options"],
                            "thesis": f"Macro contrarian: Fear & Greed is {fng:.0f} (extreme greed) with VIX only {vix:.1f}. Complacency like this precedes pullbacks, so it buys a small SPY put as a hedge-style bet."})
        return sorted(out, key=lambda x: -x["score"])


TRADERS = [MomentumMo(), ReversionRae(), CatalystCal()]
