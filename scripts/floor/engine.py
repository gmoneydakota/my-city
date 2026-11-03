"""One run of the Trading Floor: refresh data, manage positions, let each trader scan and trade, write results."""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import clock, ledger
from .options import pick_contract
from .quant import bs_price, est_iv, features, pick_strike
from .sources import INDEXES, SECTORS, pmap, sentiment
from .traders import ETFS, TRADERS

MAX_OPTIONS_OPEN = 3
RISK_FREE_DEFAULT = 0.043


# ---------------------------------------------------------------- storage

class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, name, default=None):
        try:
            return json.loads((self.root / name).read_text())
        except Exception:  # noqa: BLE001
            return default

    def write(self, name, data):
        tmp = self.root / (name + ".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":"), default=str))
        tmp.replace(self.root / name)


# ---------------------------------------------------------------- context

class Ctx:
    def __init__(self, now, minutes, feat, quote, macro, regime, earn_today, earn_tomorrow, provider):
        self.now, self.minutes, self.feat, self.quote, self.macro, self.regime = now, minutes, feat, quote, macro, regime
        self.earnings_today, self.earnings_tomorrow = earn_today, earn_tomorrow
        self._p, self._news = provider, {}

    def news_for(self, symbols):
        need = [s for s in symbols if s not in self._news]
        for s, v in pmap(self._p.news, need, workers=6).items():
            self._news[s] = v or []
        return {s: self._news.get(s, []) for s in symbols}


def build_features(provider, universe, today: date, log):
    t0 = time.time()
    raw = pmap(lambda s: provider.daily(s), universe, workers=8)
    spy_bars = raw.get("SPY") or []
    spy_bars = [b for b in spy_bars if b["date"] < today.isoformat()]
    spy_r60 = None
    if len(spy_bars) > 61:
        spy_r60 = (spy_bars[-1]["close"] / spy_bars[-61]["close"] - 1) * 100
    feats, failed = {}, 0
    for s, bars in raw.items():
        if not bars:
            failed += 1
            continue
        bars = [b for b in bars if b["date"] < today.isoformat()]
        f = features(bars, spy_r60 or 0.0)
        if f:
            feats[s] = f
        else:
            failed += 1
    rs = sorted(f["rs60"] for f in feats.values() if f["rs60"] is not None)
    for f in feats.values():
        f["rs_rank"] = round(sum(1 for x in rs if x <= f["rs60"]) / len(rs) * 100, 1) if rs and f["rs60"] is not None else None
    n = len(feats) or 1
    breadth = {"pct_above_50": round(100 * sum(1 for f in feats.values() if f["close"] > f["sma50"]) / n, 1),
               "pct_above_200": round(100 * sum(1 for f in feats.values() if f.get("sma200") and f["close"] > f["sma200"]) / n, 1),
               "near_20d_highs": sum(1 for f in feats.values() if f["close"] >= f["hh20"] * 0.98),
               "near_20d_lows": sum(1 for f in feats.values() if f["close"] <= f["ll20"] * 1.02)}
    return {"built_for": today.isoformat(), "built": datetime.now(timezone.utc).isoformat(), "seconds": round(time.time() - t0, 1),
            "failed": failed, "breadth": breadth, "features": feats}


def derive_quote(snap, f, minutes):
    prev = f["close"] if f else snap.get("prev_close")
    if not prev:
        return None
    p = snap["price"]
    q = dict(snap)
    q["prev_close"] = prev
    q["chg_pct"] = round((p / prev - 1) * 100, 3)
    q["gap_pct"] = round((snap["open"] / prev - 1) * 100, 3) if snap.get("open") else 0.0
    frac = clock.volume_fraction(minutes)
    q["vol_pace"] = round(snap["volume"] / (f["avgvol"] * frac), 2) if f and f.get("avgvol") and frac >= 0.12 and snap.get("volume") else None
    return q


def classify_regime(macro, breadth, spy_feat, spy_price):
    pts, why = 0, []
    if spy_feat and spy_price:
        if spy_feat.get("sma50") and spy_price > spy_feat["sma50"]:
            pts += 1; why.append("SPY above 50-day")
        elif spy_feat.get("sma50"):
            pts -= 1; why.append("SPY below 50-day")
        if spy_feat.get("sma200") and spy_price > spy_feat["sma200"]:
            pts += 1; why.append("SPY above 200-day")
    vix = macro.get("vix")
    if vix:
        if vix < 18: pts += 1; why.append(f"VIX calm ({vix:.1f})")
        elif vix > 28: pts -= 2; why.append(f"VIX elevated ({vix:.1f})")
        elif vix > 22: pts -= 1; why.append(f"VIX uneasy ({vix:.1f})")
    fng = (macro.get("fng") or {}).get("score")
    if fng is not None:
        if fng >= 55: pts += 1; why.append(f"Fear & Greed {fng:.0f}")
        elif fng <= 30: pts -= 1; why.append(f"Fear & Greed {fng:.0f}")
    b = breadth.get("pct_above_50")
    if b is not None:
        if b >= 55: pts += 1; why.append(f"{b:.0f}% of stocks above 50-day")
        elif b <= 35: pts -= 1; why.append(f"only {b:.0f}% of stocks above 50-day")
    return ("risk-on" if pts >= 3 else "risk-off" if pts <= 0 else "neutral"), pts, why


# ---------------------------------------------------------------- options helpers

def next_expiry(today: date, min_days=28) -> date:
    d = today + timedelta(days=min_days)
    while d.weekday() != 4 or not clock.is_session(d):
        d += timedelta(days=1)
    return d


def option_mark(pos, spot, today: date, minutes: int, vix, rf):
    o = pos["option"]
    exp = date.fromisoformat(o["expiry"])
    T = max((exp - today).days, 0) / 365.0
    iv = o["iv"] * min(1.5, max(0.7, ((vix or o["vix0"]) / o["vix0"]) ** 0.5))
    return bs_price(spot, o["strike"], T, rf, iv, o["cp"])


# ---------------------------------------------------------------- the floor

STALE_SECONDS = 20 * 60        # a quote older than this during the session is not traded on
PRICE_CHECK_TOLERANCE = 0.015  # feed vs verified reference price


class Floor:
    def __init__(self, provider, store: Store, demo=False):
        self.p, self.store, self.demo = provider, store, demo
        self.state = store.read("state.json") or {"accounts": {t.id: ledger.new_account(t.id) for t in TRADERS}, "bench": {}, "feed": [], "runs": 0}
        for t in TRADERS:
            self.state["accounts"].setdefault(t.id, ledger.new_account(t.id))
            self.state["accounts"][t.id].setdefault("orders", [])
        self.info = {}

    @staticmethod
    def _stale(snap, now, ph):
        a = snap.get("asof") if snap else None
        return bool(ph == "open" and a and a > 1e9 and now.timestamp() - a > STALE_SECONDS)

    # -- public
    def run(self, now: datetime, force_phase=None, manage_only=False, log=print):
        ph, minutes = clock.phase(now)
        if force_phase:
            ph = force_phase
            minutes = 390 if ph == "post" else max(minutes, 5)
        today = now.astimezone(clock.ET).date()
        ts = now.astimezone(timezone.utc).isoformat(timespec="seconds")
        if ph in ("closed", "pre"):
            log(f"market is {ph} ({today}); nothing to do")
            return {"phase": ph, "changed": False}
        accts = self.state["accounts"]
        if ph == "post" and all(today.isoformat() in a["daily_close"] for a in accts.values()) and not force_phase:
            log("end-of-day already recorded; nothing to do")
            return {"phase": ph, "changed": False}
        if hasattr(self.p, "new_run"):
            self.p.new_run()
        self.info = {"mode": "manage" if manage_only else "full", "stale_dropped": 0, "price_checks": 0, "option_sources": {}}

        spy = self.p.intraday("SPY")
        if spy is None:   # circuit breaker: don't hammer 500 symbols when the price feed is down
            log("could not get a live SPY quote (price feed down?); skipping this run, nothing changed")
            return {"phase": ph, "changed": False, "error": "price feed unreachable"}
        if self._stale(spy, now, ph):
            log("SPY quote is more than 20 minutes old (feed delayed or frozen); skipping this run, nothing changed")
            return {"phase": ph, "changed": False, "error": "stale quotes"}

        fc = self.store.read("features.json") or {}
        fresh = fc.get("built_for") == today.isoformat()
        if manage_only and not (ph == "open" and fresh):
            manage_only = False
            self.info["mode"] = "full"
        held = {pos["symbol"] for a in accts.values() for pos in a["positions"]}
        universe, usrc = [], ""
        if manage_only:
            feat = fc["features"]
            want = sorted(held | {"SPY", "^VIX"})
        else:
            universe, usrc = self.p.universe()
            extra = [s for s in list(INDEXES) + list(SECTORS) if s not in universe]
            if not fresh:
                log(f"building daily features for {len(universe)} symbols ...")
                fc = build_features(self.p, universe, today, log)
                self.store.write("features.json", fc)
                log(f"  features for {len(fc['features'])} symbols in {fc['seconds']}s ({fc['failed']} failed)")
            feat = fc["features"]
            want = sorted(set(universe) | set(extra) | held)
        if "SPY" in feat:
            self.state["bench"].setdefault(feat["SPY"]["date"], feat["SPY"]["close"])

        t0 = time.time()
        snaps = pmap(self.p.intraday, want, workers=8)
        ok = sum(1 for v in snaps.values() if v)
        log(f"quotes: {ok}/{len(want)} in {time.time() - t0:.0f}s ({self.info['mode']} run)")
        quote = {}
        for s, sn in snaps.items():
            if not sn:
                continue
            if not s.startswith("^") and self._stale(sn, now, ph):
                self.info["stale_dropped"] += 1
                continue
            q = derive_quote(sn, feat.get(s), minutes)
            if q:
                quote[s] = q
        if ok < max(2 if manage_only else 5, 0.3 * len(want)):
            log("too few quotes came back; skipping trading this run (positions unchanged)")
            return {"phase": ph, "changed": False, "error": "no quotes"}

        spy_state = (quote.get("SPY") or {}).get("state")
        if ph == "open" and spy_state in ("CLOSED", "POST", "POSTPOST"):
            log(f"Yahoo reports the market as {spy_state} (early close?): treating this as the end of the day")
            ph, minutes = "post", 390
            manage_only = False
            if all(today.isoformat() in a["daily_close"] for a in accts.values()):
                return {"phase": ph, "changed": False}
        macro = {} if manage_only else self.p.macro()
        vq = quote.get("^VIX")
        if vq:
            macro["vix"], macro["vix_chg"] = vq["price"], vq["chg_pct"]
        tq = quote.get("^TNX")
        if tq and not macro.get("ten_year"):
            macro["ten_year"] = tq["price"] / 10 if tq["price"] > 20 else tq["price"]
        rf = (macro.get("ten_year") or self.state.get("rf_pct") or RISK_FREE_DEFAULT * 100) / 100
        self.state["rf_pct"] = rf * 100
        if manage_only:
            regime, rpts, rwhy, earn_today, earn_tom = self.state.get("regime", "neutral"), 0, [], set(), set()
        else:
            regime, rpts, rwhy = classify_regime(macro, fc["breadth"], feat.get("SPY"), (quote.get("SPY") or {}).get("price"))
            self.state["regime"] = regime
            tomorrow = today + timedelta(days=1)
            while not clock.is_session(tomorrow):
                tomorrow += timedelta(days=1)
            earn_today = self.p.earnings(today.isoformat()) or set()
            earn_tom = self.p.earnings(tomorrow.isoformat()) or set()
        ctx = Ctx(now, minutes, feat, quote, macro, regime, earn_today, earn_tom, self.p)
        ctx.rf = rf

        events = []
        for t in TRADERS:
            a = accts[t.id]
            try:   # one trader's bug must never stop the others
                self._mark(a, ctx, today, ts)
                events += self._exits(a, t, ctx, today, ts, force_close=(ph == "post" or minutes >= 355))
                if ph == "open" and not manage_only:
                    events += self._entries(a, t, ctx, today, ts)
                elif manage_only:
                    a["last_manage"] = ts
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                a["last_run"] = {"ts": ts, "regime": regime, "candidates": [], "notes": [f"ERROR during this run: {type(exc).__name__}: {exc}. Positions were left as they were."]}
            self._mark(a, ctx, today)
            ledger.snapshot(a, ts)
            if ph == "post":
                a["daily_close"][today.isoformat()] = round(ledger.equity(a), 2)
        if ph == "post" and "SPY" in quote:
            self.state["bench"][today.isoformat()] = quote["SPY"]["price"]
        self.state["feed"] = (events + self.state["feed"])[:150]
        self.state["runs"] += 1
        self.state["last_run"] = {"ts": ts, "phase": ph, "minutes": minutes, "mode": self.info["mode"]}
        self._write_outputs(now, ph, ctx, fc, universe, usrc, quote, rwhy, rpts, today, write_market=not manage_only)
        log(f"done: {len(events)} trade events, regime {regime}")
        return {"phase": ph, "changed": True, "events": len(events)}

    # -- marking & exits
    def _mark(self, a, ctx, today, ts=None):
        vix = ctx.macro.get("vix")
        for p in a["positions"]:
            q = ctx.quote.get(p["symbol"])
            if not q:
                continue
            if p["kind"] == "stock":
                p["mark"] = round(q["price"], 4)
            else:
                o = p["option"]
                rq = self.p.option_quote(p["symbol"], o["contract"]) if o.get("contract") and o.get("source") not in (None, "model") and hasattr(self.p, "option_quote") else None
                if rq and rq.get("bid") and rq.get("ask") and rq["ask"] >= rq["bid"] > 0:
                    p["mark"], p["bid"], p["ask"], p["mark_src"] = round((rq["bid"] + rq["ask"]) / 2, 4), rq["bid"], rq["ask"], o["source"]
                    if rq.get("delta") is not None:
                        p["delta"] = rq["delta"]
                else:
                    p["mark"] = round(max(option_mark(p, q["price"], today, ctx.minutes, vix, ctx.rf), 0.0), 4)
                    p["mark_src"] = "model"
                    p.pop("bid", None), p.pop("ask", None)
                p["spot"] = round(q["price"], 4)
            p["high_water"] = max(p.get("high_water", p["entry"]), p["mark"])
            if ts:
                tr = p.setdefault("track", [])
                tr.append([ts, p["mark"], round(q["price"], 4)])
                if len(tr) > 400:
                    del tr[1:len(tr) - 399]

    def _exits(self, a, t, ctx, today, ts, force_close):
        ev = []
        for p in list(a["positions"]):
            q = ctx.quote.get(p["symbol"])
            if not q:
                continue
            age = (today - datetime.fromisoformat(p["entry_ts"]).astimezone(clock.ET).date()).days
            m, reason = p["mark"], None
            if p["kind"] == "stock":
                risk = p.get("risk") or max(p["entry"] - p["stop"], 1e-9)
                if m >= p["entry"] + 2 * risk:
                    p["stop"] = max(p["stop"], p["high_water"] - risk)
                elif m >= p["entry"] + risk:
                    p["stop"] = max(p["stop"], p["entry"])
                if m <= p["stop"]:
                    reason = "stop hit" if p["stop"] < p["entry"] else "trailing stop"
                elif m >= p["target"]:
                    reason = "target hit"
            else:
                chg = (m / p["entry"] - 1) * 100
                dte = (date.fromisoformat(p["option"]["expiry"]) - today).days
                if chg <= p["stop"]:
                    reason = "premium stop"
                elif chg >= p["target"]:
                    reason = "target hit"
                elif dte <= 5:
                    reason = "too close to expiry"
            if not reason and p["horizon"] == "day" and force_close:
                reason = "day trade closed at the bell"
            if not reason and age >= p["max_days"] and (force_close or p["max_days"] > 1):
                reason = "time stop"
            if reason:
                real = p["kind"] != "stock" and p.get("bid") and p.get("mark_src") not in (None, "model")
                tr = ledger.close_position(a, p, m, ts, reason, fill=p["bid"] if real else None, src=p.get("mark_src", "model") if p["kind"] != "stock" else "yahoo")
                ev.append(self._event(t, "exit", tr["symbol"], f"{tr['reason']}: sold {tr['symbol']} {tr['kind']} {tr['pnl']:+,.0f} ({tr['ret_pct']:+.1f}%)", ts, pnl=tr["pnl"]))
        return ev

    def _event(self, t, typ, sym, text, ts, **kw):
        return {"ts": ts, "trader": t.id, "type": typ, "symbol": sym, "text": text, **kw}

    # -- entries
    def _entries(self, a, t, ctx, today, ts):
        ev, eq = [], ledger.equity(a)
        prev = ledger._baseline(a["daily_close"], today, a["start_cash"])
        day_pct = (eq / prev - 1) * 100
        notes, taken = [], 0
        run = {"ts": ts, "regime": ctx.regime, "equity": round(eq, 2), "day_pct": round(day_pct, 2), "candidates": [], "notes": notes}
        window_ok = t.first_entry_min <= ctx.minutes <= t.last_entry_min
        if not window_ok:
            notes.append(f"Outside {t.name}'s entry window (minutes {t.first_entry_min}-{t.last_entry_min} of the session).")
        if day_pct <= t.loss_halt_pct:
            notes.append(f"Daily loss limit reached ({day_pct:.1f}%): no new trades today.")
            window_ok = False
        sigs = t.scan(ctx, a)
        held = {p["symbol"] for p in a["positions"]}
        n_opt = sum(1 for p in a["positions"] if p["kind"] != "stock")
        for s in sigs[:12]:
            c = {"symbol": s["symbol"], "kind": s["kind"], "score": round(s["score"], 2), "horizon": s["horizon"], "thesis": s["thesis"], "action": None,
                 "price": ctx.quote[s["symbol"]]["price"], "stop": s.get("stop"), "target": s.get("target"), "stop_pct": s.get("stop_pct"),
                 "target_pct": s.get("target_pct"), "premium_frac": s.get("premium_frac"), "max_days": s.get("max_days"), "tags": s.get("tags", [])}
            run["candidates"].append(c)
            if not window_ok: c["action"] = "waiting (outside entry window)"; continue
            if taken >= t.max_new_per_run: c["action"] = "passed: max new trades this run"; continue
            if len(a["positions"]) >= t.max_positions: c["action"] = "passed: portfolio full"; continue
            if s["symbol"] in held: c["action"] = "passed: already holding"; continue
            cd = a["cooldown"].get(s["symbol"])
            if cd and (today - date.fromisoformat(cd)).days < 2: c["action"] = "passed: recent loss in this name"; continue
            if s["kind"] != "stock" and n_opt >= MAX_OPTIONS_OPEN: c["action"] = "passed: option limit"; continue
            pos, why = self._open(a, s, ctx, today, ts, eq)
            if pos:
                c["action"] = "BOUGHT"
                taken += 1
                held.add(s["symbol"])
                n_opt += s["kind"] != "stock"
                what = f"{pos['qty']} {'shares' if pos['kind'] == 'stock' else 'contracts'}" + (f" ({pos['option']['cp'].upper()} {pos['option']['strike']:g} exp {pos['option']['expiry']})" if pos.get("option") else "")
                ev.append(self._event(t, "entry", pos["symbol"], f"Bought {what} of {pos['symbol']} at ${pos['entry']:,.2f}", ts, thesis=pos["thesis"]))
            else:
                c["action"] = f"passed: {why}"
        if not run["candidates"]:
            notes.append("No setups matched this trader's rules right now.")
        a["last_run"] = run
        return ev

    def _open(self, a, s, ctx, today, ts, eq):
        """Returns (position, reason_if_not)."""
        q = ctx.quote[s["symbol"]]
        f = ctx.feat.get(s["symbol"]) or {}
        price, psrc = q["price"], "yahoo"
        v = self.p.verify_price(s["symbol"], price) if hasattr(self.p, "verify_price") else None
        if v:
            self.info["price_checks"] += 1
            if abs(v["ref"] / price - 1) > PRICE_CHECK_TOLERANCE:
                return None, f"price check failed (feed ${price:,.2f} vs {v['src']} ${v['ref']:,.2f})"
            price, psrc = v["ref"], v["src"]
        if s["kind"] == "stock":
            risk = price - s["stop"]
            if risk <= 0 or s["stop"] <= 0:
                return None, "price already through the stop"
            qty = int(min(eq * s["risk_frac"] / risk, eq * 0.10 / price, a["cash"] / (price * 1.001)))
            if qty < 1:
                return None, "could not size (cash/price)"
            pos = ledger.open_position(a, kind="stock", symbol=s["symbol"], qty=qty, price=price, ts=ts, horizon=s["horizon"], stop=round(s["stop"], 4),
                                       target=round(s["target"], 4), thesis=s["thesis"], tags=s.get("tags"), max_days=s["max_days"], underlying=price, src=psrc)
            if pos:
                pos["risk"] = round(pos["entry"] - pos["stop"], 4)
            return pos, "not enough cash"
        cp = s["kind"]
        vix = ctx.macro.get("vix") or 18
        budget = min(eq * s["premium_frac"], a["cash"] * 0.95)
        chain, csrc = self.p.option_chain(s["symbol"]) if hasattr(self.p, "option_chain") else (None, None)
        if chain:   # REAL quotes: pay the ask, tradable contracts only
            c = pick_contract(chain, cp, price, today)
            if not c:
                return None, "no liquid option contract (needs a tight two-sided quote and open interest)"
            qty = int(budget // (c["ask"] * 100 + ledger.OPT_COMMISSION))
            if qty < 1:
                return None, "premium budget too small for one contract"
            iv = c.get("iv") or est_iv(f.get("hv20"), f.get("hv60"), vix)
            opt = {"cp": cp, "strike": c["strike"], "expiry": c["expiry"], "iv": round(iv, 4), "vix0": vix, "model_priced": False, "source": csrc,
                   "contract": c["contract"], "bid0": c["bid"], "ask0": c["ask"], "delta0": c.get("delta"), "oi": c.get("oi"), "entry_spot": round(price, 2)}
            self.info["option_sources"][csrc] = self.info["option_sources"].get(csrc, 0) + 1
            return ledger.open_position(a, kind=cp, symbol=s["symbol"], qty=qty, price=(c["bid"] + c["ask"]) / 2, fill=c["ask"], ts=ts, horizon=s["horizon"], stop=s["stop_pct"],
                                        target=s["target_pct"], thesis=s["thesis"], tags=s.get("tags"), option=opt, max_days=s["max_days"], underlying=price, src=csrc), "not enough cash"
        iv = est_iv(f.get("hv20"), f.get("hv60"), vix)
        exp = next_expiry(today)
        K = pick_strike(price, cp, 2.0)
        T = (exp - today).days / 365
        mid = bs_price(price, K, T, ctx.rf, iv, cp)
        if mid < 0.35:
            return None, "model premium too small"
        qty = int(budget // (mid * (1 + ledger.OPT_HALF_SPREAD) * 100 + ledger.OPT_COMMISSION))
        if qty < 1:
            return None, "premium budget too small for one contract"
        opt = {"cp": cp, "strike": K, "expiry": exp.isoformat(), "iv": round(iv, 4), "vix0": vix, "model_priced": True, "source": "model", "contract": None, "entry_spot": round(price, 2)}
        self.info["option_sources"]["model"] = self.info["option_sources"].get("model", 0) + 1
        return ledger.open_position(a, kind=cp, symbol=s["symbol"], qty=qty, price=mid, ts=ts, horizon=s["horizon"], stop=s["stop_pct"], target=s["target_pct"],
                                    thesis=s["thesis"], tags=s.get("tags"), option=opt, max_days=s["max_days"], underlying=price, src="model"), "not enough cash"

    # -- outputs
    def _write_outputs(self, now, ph, ctx, fc, universe, usrc, quote, rwhy, rpts, today, write_market=True):
        accts = self.state["accounts"]
        self.store.write("state.json", self.state)
        board = {"generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"), "demo": self.demo, "phase": ph, "date": today.isoformat(),
                 "start_cash": ledger.START_CASH, "traders": [], "champions": ledger.champions(accts), "run_info": self.info,
                 "last_full_run": self.state["last_run"]["ts"] if self.info.get("mode") == "full" else (self.store.read("leaderboard.json") or {}).get("last_full_run")}
        allorders = []
        for t in TRADERS:
            a = accts[t.id]
            tr = a["trades"]
            orders = a.get("orders", [])
            allorders += [{**o, "trader": t.id} for o in orders[-70:]]
            board["traders"].append({
                **t.profile(), "equity": round(ledger.equity(a), 2), "cash": round(a["cash"], 2), "windows": ledger.window_returns(a, today),
                "open_positions": a["positions"], "recent_trades": tr[-30:][::-1], "equity_history": a["equity_history"],
                "daily_close": a["daily_close"], "last_run": a["last_run"], "last_manage": a.get("last_manage"), "scorecard": ledger.scorecard(a, self.state["bench"]),
                "stats": {"trades": len(tr), "wins": sum(1 for x in tr if x["pnl"] > 0), "realized": round(sum(x["pnl"] for x in tr), 2),
                          "options_trades": sum(1 for x in tr if x["kind"] != "stock")}})
        board["orders"] = sorted(allorders, key=lambda o: o["ts"], reverse=True)[:160]
        board["bench"] = self.state["bench"]
        board["feed"] = self.state["feed"][:60]
        self.store.write("leaderboard.json", board)
        if not write_market:
            return
        # market overview
        liquid = [(s, q) for s, q in quote.items() if s in ctx.feat and s not in ETFS and ctx.feat[s]["dollar_vol"] >= 25e6 and ctx.feat[s]["close"] >= 10]
        mv = lambda s, q: {"symbol": s, "price": q["price"], "chg_pct": q["chg_pct"], "vol_pace": q.get("vol_pace"), "rs_rank": ctx.feat[s].get("rs_rank")}
        adv = sum(1 for _, q in liquid if q["chg_pct"] > 0)
        mkt = {"generated_at": board["generated_at"], "demo": self.demo, "phase": ph, "regime": ctx.regime, "regime_points": rpts, "regime_reasons": rwhy,
               "macro": ctx.macro, "breadth": {**fc["breadth"], "advancers": adv, "decliners": len(liquid) - adv},
               "indices": [{"symbol": s, "name": n, "price": quote[s]["price"], "chg_pct": quote[s]["chg_pct"]} for s, n in INDEXES.items() if s in quote],
               "sectors": sorted([{"symbol": s, "name": n, "chg_pct": quote[s]["chg_pct"], "r20": ctx.feat.get(s, {}).get("r20")} for s, n in SECTORS.items() if s in quote],
                                 key=lambda x: -x["chg_pct"]),
               "gainers": [mv(s, q) for s, q in sorted(liquid, key=lambda x: -x[1]["chg_pct"])[:10]],
               "losers": [mv(s, q) for s, q in sorted(liquid, key=lambda x: x[1]["chg_pct"])[:10]],
               "unusual_volume": [mv(s, q) for s, q in sorted([x for x in liquid if x[1].get("vol_pace")], key=lambda x: -x[1]["vol_pace"])[:10]],
               "earnings_today": sorted(ctx.earnings_today)[:60],
               "headlines": [{**h, "tone": sentiment([h["title"]])} for h in (self.p.market_news() or [])[:12]],
               "universe": {"size": len(universe), "source": usrc, "with_features": len(ctx.feat), "quotes": len(quote)},
               "sources": self.p.source_status(), "disclosure": "Paper trading only. Options are priced with a Black-Scholes model, not live quotes."}
        self.store.write("market.json", mkt)
