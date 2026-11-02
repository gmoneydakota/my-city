"""Data providers: Live (public APIs) and Demo (synthetic, clearly labelled)."""
from __future__ import annotations

import math
import random
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from . import clock, sources
from .sources import FALLBACK_UNIVERSE, INDEXES, SECTORS


class _Log:
    def __init__(self):
        self.d, self.lock = {}, threading.Lock()

    def rec(self, name, ok, err=None, note=""):
        with self.lock:
            e = self.d.setdefault(name, {"name": name, "ok": 0, "fail": 0, "last_error": None, "note": note})
            e["ok" if ok else "fail"] += 1
            if not ok and err:
                e["last_error"] = str(err)[:160]

    def status(self):
        out = []
        for e in self.d.values():
            tot = e["ok"] + e["fail"]
            out.append({**e, "status": "ok" if e["ok"] and e["fail"] <= 0.2 * tot else "partial" if e["ok"] else "down"})
        return sorted(out, key=lambda x: x["name"])


class LiveProvider:
    name = "live"

    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.log = _Log()

    def source_status(self):
        return self.log.status()

    def universe(self):
        syms, src = sources.load_universe(self.dir / "universe.json")
        self.log.rec("Universe (S&P 500 list)", src != "built-in list", None if src != "built-in list" else "using built-in list", src)
        return syms, src

    def daily(self, sym):
        try:
            bars = sources.daily_bars(sym, 1)
            self.log.rec("Daily prices (Yahoo Finance → Stooq)", True)
            return bars
        except Exception as e:  # noqa: BLE001
            self.log.rec("Daily prices (Yahoo Finance → Stooq)", False, e)
            return None

    def intraday(self, sym):
        try:
            r = sources.yahoo_intraday(sym)
            self.log.rec("Live quotes & 5-min bars (Yahoo Finance)", r is not None, None if r else "empty")
            return r
        except Exception as e:  # noqa: BLE001
            self.log.rec("Live quotes & 5-min bars (Yahoo Finance)", False, e)
            return None

    def macro(self):
        m = {}
        for key, series in (("ten_year", "DGS10"), ("two_year", "DGS2"), ("hy_spread", "BAMLH0A0HYM2")):
            try:
                m[key], m[key + "_prev"] = sources.fred(series)
                self.log.rec("Treasury yields & credit spreads (FRED)", True)
            except Exception as e:  # noqa: BLE001
                self.log.rec("Treasury yields & credit spreads (FRED)", False, e)
        if m.get("ten_year") is not None and m.get("two_year") is not None:
            m["curve_10y_2y"] = round(m["ten_year"] - m["two_year"], 2)
        try:
            m["fng"] = sources.fear_greed()
            self.log.rec("Fear & Greed index (CNN)", bool(m["fng"]), None if m["fng"] else "unexpected format")
        except Exception as e:  # noqa: BLE001
            m["fng"] = None
            self.log.rec("Fear & Greed index (CNN)", False, e)
        return m

    def news(self, sym):
        try:
            r = sources.news(sym)
            self.log.rec("Headlines (Google News + Yahoo Finance RSS)", bool(r), None if r else "no headlines")
            return r
        except Exception as e:  # noqa: BLE001
            self.log.rec("Headlines (Google News + Yahoo Finance RSS)", False, e)
            return []

    def market_news(self):
        try:
            r = sources.market_news()
            self.log.rec("Market headlines (Google News RSS)", True)
            return r
        except Exception as e:  # noqa: BLE001
            self.log.rec("Market headlines (Google News RSS)", False, e)
            return []

    def earnings(self, day):
        try:
            r = sources.earnings_on(day)
            self.log.rec("Earnings calendar (Nasdaq)", True)
            return r
        except Exception as e:  # noqa: BLE001
            self.log.rec("Earnings calendar (Nasdaq)", False, e)
            return set()


# ---------------------------------------------------------------- demo

class DemoProvider:
    """Synthetic random-walk market so the whole pipeline can be tested and shown with no internet.
    Prices are NOT real. Ticker names are reused only so the screens look familiar."""
    name = "demo"

    def __init__(self, seed=7, n_symbols=120, sim_days=40, end=date(2026, 10, 30)):
        self.seed, self.log, self.now = seed, _Log(), None
        rng = random.Random(seed)
        self.syms = [s for s in dict.fromkeys(FALLBACK_UNIVERSE)][:n_symbols]
        self.extra = ["SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "UUP", "^VIX", "^TNX"] + list(SECTORS)
        # trading calendar: 330 history days + sim_days, ending at `end`
        days, d = [], end
        while len(days) < 330 + sim_days:
            if clock.is_session(d):
                days.append(d)
            d -= timedelta(days=1)
        self.days = sorted(days)
        self.first_sim = self.days[-sim_days] if sim_days else None
        self.index = {d.isoformat(): i for i, d in enumerate(self.days)}
        # market factor with regimes
        self.mkt, regime = [], 0.0004
        for i in range(len(self.days)):
            if i % 45 == 0:
                regime = rng.choice([0.0012, 0.0004, -0.0006, 0.0008])
            self.mkt.append(rng.gauss(regime, 0.0095))
        self.events = {}   # (sym, iso) -> dict(gap, vol_mult, tone, earnings)
        self.series = {}
        for s in self.syms + self.extra:
            self.series[s] = self._gen(s, rng)

    def _gen(self, s, rng):
        etf = s in self.extra
        base = rng.uniform(25, 450) if not etf else rng.uniform(40, 500)
        if s == "^VIX":
            base = 17
        if s == "^TNX":
            base = 42
        if s in ("SPY", "QQQ", "IWM", "DIA"):
            base = {"SPY": 600, "QQQ": 520, "IWM": 230, "DIA": 440}[s]
        beta = rng.uniform(0.6, 1.7) if not etf else 1.0
        idio = rng.uniform(0.008, 0.022) if not etf else 0.004
        avgvol = rng.uniform(2e6, 30e6) * (3 if etf else 1)
        bars, px, mom = [], base, 0.0
        for i, d in enumerate(self.days):
            iso = d.isoformat()
            r = beta * self.mkt[i] + rng.gauss(0, idio) + mom * 0.05
            if s == "^VIX":
                vol10 = (sum(x * x for x in self.mkt[max(0, i - 10):i + 1]) / 11) ** 0.5
                target = max(11.0, min(45.0, 9 + 900 * vol10))
                r = (target / px - 1) * 0.5 + rng.gauss(0, 0.03)
            elif s == "^TNX":
                r = rng.gauss(0, 0.01)
            gap = 0.0
            vm = max(0.3, rng.lognormvariate(0, 0.25))
            if not etf and rng.random() < 0.035 and i > 60:
                gap = rng.choice([-1, 1]) * rng.uniform(0.03, 0.08)
                vm *= rng.uniform(2.2, 4.0)
                self.events[(s, iso)] = {"gap": gap, "tone": 1 if gap > 0 else -1, "earn": rng.random() < 0.3}
            r += gap
            mom = 0.7 * mom + r
            o = px * (1 + gap + rng.gauss(0, idio * 0.25))
            c = o * (1 + (r - gap) * 0.9)
            h, l = max(o, c) * (1 + abs(rng.gauss(0, idio * 0.4))), min(o, c) * (1 - abs(rng.gauss(0, idio * 0.4)))
            bars.append({"date": iso, "open": o, "high": h, "low": l, "close": c, "volume": avgvol * vm, "vol": idio})
            px = max(c, 1.0)
        return bars

    def set_time(self, now: datetime):
        self.now = now

    def _today(self):
        return self.now.astimezone(clock.ET).date().isoformat()

    def source_status(self):
        return [{"name": "DEMO: synthetic random-walk market (no real data)", "ok": 1, "fail": 0, "status": "demo", "last_error": None, "note": ""}]

    def universe(self):
        return list(self.syms), "demo"

    def daily(self, sym):
        today = self._today()
        return [{k: b[k] for k in ("date", "open", "high", "low", "close", "volume")} for b in self.series.get(sym, []) if b["date"] <= today]

    def intraday(self, sym):
        today = self._today()
        i = self.index.get(today)
        if i is None or sym not in self.series:
            return None
        b, prev = self.series[sym][i], self.series[sym][i - 1]
        _, minutes = clock.phase(self.now)
        minutes = max(5, min(390, minutes))
        n_total, n = 78, max(1, min(78, minutes // 5))
        rng = random.Random(f"{self.seed}:{sym}:{today}")
        steps = [rng.gauss(0, 1) for _ in range(n_total)]
        # Brownian bridge from open to close
        cum, path = 0.0, []
        for k in range(n_total):
            cum += steps[k]
            path.append(cum)
        end = path[-1]
        sig = b["vol"] * 0.6 / math.sqrt(n_total)
        pts = [b["open"] * math.exp(sig * (path[k] - (k + 1) / n_total * end)) * (b["close"] / b["open"]) ** ((k + 1) / n_total) for k in range(n_total)]
        seen = pts[:n]
        price = seen[-1] if minutes < 390 else b["close"]
        vol = b["volume"] * clock.volume_fraction(minutes)
        first = seen[:6]
        return {"price": price, "prev_close": prev["close"], "open": b["open"], "high": max(seen + [b["open"]]), "low": min(seen + [b["open"]]),
                "volume": vol, "vwap": sum(seen) / len(seen), "or_high": max(first), "or_low": min(first), "n_bars": n, "asof": 0, "state": "REGULAR"}

    def macro(self):
        today = self._today()
        i = self.index.get(today, len(self.days) - 1)
        spy = self.series["SPY"]
        r20 = (spy[i - 1]["close"] / spy[i - 21]["close"] - 1) * 100
        vix = self.series["^VIX"][i - 1]["close"]
        fng = max(3, min(97, 50 + r20 * 2.5 - (vix - 18) * 1.5))
        return {"ten_year": max(3.0, min(5.5, 4.2 + (self.series["^TNX"][i - 1]["close"] - 42) / 10)), "two_year": 3.9, "hy_spread": 3.1, "curve_10y_2y": 0.3,
                "fng": {"score": round(fng, 1), "rating": "demo"}}

    def news(self, sym):
        today = self._today()
        ev = self.events.get((sym, today))
        if not ev:
            return [{"title": f"{sym} shares little changed as market digests data", "source": "demo", "link": "", "time": None}]
        up = ev["tone"] > 0
        t = ([f"{sym} beats estimates, raises outlook; analysts upgrade", f"{sym} surges on record growth and strong demand", f"{sym} wins major contract, shares jump"] if up else
             [f"{sym} misses estimates and cuts guidance; analysts downgrade", f"{sym} plunges on probe and lawsuit concerns", f"{sym} warns of weak demand, shares slump"])
        return [{"title": x, "source": "demo", "link": "", "time": None} for x in t]

    def market_news(self):
        return [{"title": "DEMO: synthetic headlines, not real news", "source": "demo", "link": "", "time": None}]

    def earnings(self, day):
        return {s for (s, d), e in self.events.items() if d == day and e["earn"]}
