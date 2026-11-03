#!/usr/bin/env python3
"""Tests for the Trading Floor. Run:  python3 scripts/test_trading_floor.py

No network needed: the live path is exercised against fake Yahoo / FRED / CNN / RSS / Nasdaq responses.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_data  # noqa: E402
from floor import clock, ledger, quant, sources  # noqa: E402
from floor.engine import Floor, Store  # noqa: E402
from floor.providers import DemoProvider, LiveProvider  # noqa: E402
from floor import options  # noqa: E402
from floor.traders import TRADERS  # noqa: E402
from trading_floor import run_demo  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# ------------------------------------------------------------------ math
@test
def put_call_parity():
    for S, K, T, sig in [(100, 100, .25, .3), (50, 55, .1, .5), (300, 280, .5, .2)]:
        c, p = quant.bs_price(S, K, T, .04, sig, "call"), quant.bs_price(S, K, T, .04, sig, "put")
        assert abs((c - p) - (S - K * math.exp(-.04 * T))) < 1e-9
    assert quant.bs_price(100, 90, 0, .04, .3, "call") == 10
    d = quant.bs_delta(100, 100, .25, .04, .3, "call")
    assert 0.5 < d < 0.65


@test
def indicators_bounded():
    up = [100 + i for i in range(40)]
    assert quant.rsi(up, 14) == 100.0
    down = list(reversed(up))
    assert quant.rsi(down, 14) < 1
    assert quant.pick_strike(187.3, "call") >= 187.3 and quant.pick_strike(187.3, "put") <= 187.3


# ------------------------------------------------------------------ parsers
@test
def parsers():
    assert sources.parse_fred_csv("DATE,DGS10\n2026-10-30,4.10\n2026-11-02,.\n2026-11-03,4.2") == (4.2, 4.1)
    assert sources.parse_fear_greed({"fear_and_greed": {"score": 23.44, "rating": "extreme fear"}})["score"] == 23.4
    assert sources.parse_fear_greed({}) is None
    assert sources.parse_earnings({"data": {"rows": [{"symbol": "BRK.B"}, {"symbol": "AAPL"}]}}) == {"BRK-B", "AAPL"}
    assert sources.sentiment(["Company beats estimates, shares surge", "analyst upgrade"]) > 0.3
    assert sources.sentiment(["Company misses, stock plunges on lawsuit and downgrade"]) < -0.3
    rss = b"<rss><channel><item><title>A jumps</title><link>x</link><pubDate>Mon, 02 Nov 2026 20:00:00 GMT</pubDate></item><item><title>Old</title><pubDate>Mon, 01 Jan 2001 20:00:00 GMT</pubDate></item></channel></rss>"
    got = sources.parse_rss(rss, max_age_hours=1e9)
    assert len(got) == 2
    assert "Old" not in [i["title"] for i in sources.parse_rss(rss, max_age_hours=24 * 365 * 5)], "old items must be dropped"
    html = '<table id="constituents"><tr><td><a class="external text" href="x">MMM</a></td><td><a class="external text" href="y">BRK.B</a></td></tr></table>'
    assert sources.parse_sp500(html) == ["MMM", "BRK-B"]


@test
def market_clock():
    assert not clock.is_session(date(2026, 11, 26))      # Thanksgiving
    assert not clock.is_session(date(2026, 12, 25))
    assert not clock.is_session(date(2026, 4, 3))        # Good Friday
    assert not clock.is_session(date(2026, 7, 3))        # July 4 observed
    assert clock.is_session(date(2026, 11, 2))
    assert clock.phase(datetime(2026, 11, 2, 14, 35, tzinfo=timezone.utc))[0] == "open"   # 9:35 ET (EST)
    assert clock.phase(datetime(2026, 11, 2, 21, 35, tzinfo=timezone.utc))[0] == "post"
    assert clock.phase(datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc))[0] == "closed"
    assert abs(clock.volume_fraction(390) - 1) < 1e-9 and clock.volume_fraction(0) == 0


# ------------------------------------------------------------------ ledger
@test
def ledger_roundtrip_and_fees():
    a = ledger.new_account("t")
    p = ledger.open_position(a, kind="stock", symbol="X", qty=100, price=50, ts="2026-11-02T15:00:00+00:00", horizon="day", stop=48, target=55, thesis="t")
    assert a["cash"] < 100000 - 5000
    tr = ledger.close_position(a, p, 50, "2026-11-02T20:00:00+00:00", "flat")
    assert tr["pnl"] < 0, "round trip at an unchanged price must cost slippage"
    assert abs(ledger.equity(a) - (100000 + tr["pnl"])) < 1e-6
    o = ledger.open_position(a, kind="call", symbol="X", qty=2, price=3.0, ts="2026-11-02T15:00:00+00:00", horizon="swing", stop=-40, target=60, thesis="t", option={"cp": "call"})
    assert o and o["entry"] > 3.0 and o["fees"] == 1.3
    assert ledger.open_position(a, kind="stock", symbol="Y", qty=10**6, price=50, ts="x", horizon="day", stop=1, target=2, thesis="t") is None, "cannot spend cash it doesn't have"


@test
def window_returns_and_champions():
    a, b = ledger.new_account("a"), ledger.new_account("b")
    a["daily_close"] = {"2026-10-30": 101000.0, "2026-11-02": 102000.0}
    b["daily_close"] = {"2026-10-30": 99000.0, "2026-11-02": 103000.0}
    a["cash"] = 102500.0
    w = ledger.window_returns(a, date(2026, 11, 3))
    assert w["day"]["pnl"] == 500 and w["week"]["pnl"] == 1500 and w["month"]["pnl"] == 1500 and w["all"]["pnl"] == 2500
    ch = ledger.champions({"a": a, "b": b})
    assert ch["day"][-1]["winner"] == "b" and ch["day"][0]["winner"] == "a"
    assert ch["month"][-1]["winner"] == "b"


@test
def scorecard_never_passes_on_thin_record():
    a = ledger.new_account("a")
    a["daily_close"] = {"2026-11-02": 120000.0}
    a["trades"] = [{"pnl": 20000.0}]
    sc = ledger.scorecard(a, {"2026-10-30": 400.0, "2026-11-02": 402.0})
    assert not sc["eligible"] and not sc["checks"]["days"]["pass"] and not sc["checks"]["trades"]["pass"]
    assert not sc["checks"]["concentration"]["pass"], "one trade made all the profit"


# ------------------------------------------------------------------ whole-engine invariants (demo market)
def _reconcile(a):
    pnl = sum(t["pnl"] for t in a["trades"])
    unreal = 0.0
    for p in a["positions"]:
        mult = 100 if p["kind"] != "stock" else 1
        unreal += p["qty"] * p["mark"] * mult - (p["qty"] * p["entry"] * mult + p["fees"])
    return a["start_cash"] + pnl + unreal


@test
def demo_simulation_invariants():
    tmp = Path(tempfile.mkdtemp())
    try:
        fl = run_demo(15, out=tmp, log=lambda *_: None)
        for t in TRADERS:
            a = fl.state["accounts"][t.id]
            assert a["cash"] >= -1e-6, f"{t.id} went negative on cash"
            assert abs(_reconcile(a) - ledger.equity(a)) < 0.5, f"{t.id}: ledger does not reconcile ({_reconcile(a)} vs {ledger.equity(a)})"
            assert len(a["positions"]) <= t.max_positions
            assert sum(1 for p in a["positions"] if p["kind"] != "stock") <= 3
            last_day = max(a["daily_close"])
            assert len(a["daily_close"]) == 15
            for p in a["positions"]:   # nothing marked as a day trade survives the close
                assert p["horizon"] != "day", f"{t.id} held a day trade overnight: {p['symbol']}"
            for tr in a["trades"]:
                assert tr["exit_ts"] >= tr["entry_ts"]
                if tr["kind"] == "stock":
                    assert tr["qty"] * tr["entry"] <= ledger.START_CASH * 1.6 * 0.105 + 1, "position bigger than ~10% of the account"
        board = json.loads((tmp / "leaderboard.json").read_text())
        assert board["demo"] and len(board["traders"]) == 3
        assert all("scorecard" in t and "windows" in t for t in board["traders"])
        mk = json.loads((tmp / "market.json").read_text())
        assert mk["regime"] in ("risk-on", "neutral", "risk-off") and mk["indices"] and mk["sectors"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def demo_is_deterministic():
    r = []
    for _ in range(2):
        tmp = Path(tempfile.mkdtemp())
        fl = run_demo(6, out=tmp, log=lambda *_: None)
        r.append([round(ledger.equity(fl.state["accounts"][t.id]), 2) for t in TRADERS])
        shutil.rmtree(tmp, ignore_errors=True)
    assert r[0] == r[1], r


@test
def daily_loss_halt():
    tmp = Path(tempfile.mkdtemp())
    try:
        prov = DemoProvider(sim_days=3)
        fl = Floor(prov, Store(tmp), demo=True)
        d = prov.first_sim
        for m in (5, 65):
            t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=clock.ET) + timedelta(minutes=m)
            prov.set_time(t)
            if m == 65:
                for acc in fl.state["accounts"].values():
                    acc["cash"] -= 5000   # force a 5% hit versus the prior close
            fl.run(t.astimezone(timezone.utc), log=lambda *_: None)
        for t in TRADERS:
            a = fl.state["accounts"][t.id]
            assert any("Daily loss limit" in n for n in a["last_run"]["notes"]), t.id
            assert all(c["action"] != "BOUGHT" for c in a["last_run"]["candidates"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def one_broken_trader_does_not_stop_the_others():
    tmp = Path(tempfile.mkdtemp())
    orig = TRADERS[0].scan
    try:
        def broken(ctx, acct):
            raise ValueError("boom")
        TRADERS[0].scan = broken
        prov = DemoProvider(sim_days=3)
        fl = Floor(prov, Store(tmp), demo=True)
        d = prov.first_sim
        t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=clock.ET) + timedelta(minutes=125)
        prov.set_time(t)
        import contextlib, io
        with contextlib.redirect_stderr(io.StringIO()):
            res = fl.run(t.astimezone(timezone.utc), log=lambda *_: None)
        assert res["changed"]
        a0, a1 = fl.state["accounts"][TRADERS[0].id], fl.state["accounts"][TRADERS[1].id]
        assert "ERROR" in a0["last_run"]["notes"][0]
        assert a1["last_run"].get("candidates") is not None and "ERROR" not in " ".join(a1["last_run"]["notes"])
    finally:
        TRADERS[0].scan = orig
        shutil.rmtree(tmp, ignore_errors=True)



# ------------------------------------------------------------------ real option quotes, price checks, freshness, light runs
CBOE_FIXTURE = {"data": {"current_price": 100.0, "options": [
    {"option": "ZZZ261204C00102000", "bid": 3.0, "ask": 3.2, "iv": 0.31, "delta": 0.45, "volume": 500, "open_interest": 2000},
    {"option": "ZZZ261204C00105000", "bid": 1.9, "ask": 2.1, "iv": 0.30, "delta": 0.33, "volume": 300, "open_interest": 1500},
    {"option": "ZZZ261204P00098000", "bid": 0.0, "ask": 0.1, "iv": 0.3, "open_interest": 4}]}}


@test
def option_parsing_and_selection():
    spot, ch = options.parse_cboe(CBOE_FIXTURE)
    assert spot == 100.0 and len(ch) == 3
    c = options.pick_contract(ch, "call", 100.0, date(2026, 11, 3))
    assert c and c["strike"] == 102.0 and c["contract"] == "ZZZ261204C00102000"
    assert options.pick_contract(ch, "put", 100.0, date(2026, 11, 3)) is None, "a one-sided quote with tiny open interest must not be tradable"
    assert options.pick_contract(ch, "call", 100.0, date(2026, 12, 1)) is None, "nothing far enough out"
    sraw = {"underlyingPrice": 100, "callExpDateMap": {"2026-12-04:31": {"102.0": [{"symbol": "ZZZ   261204C00102000", "bid": 3.0, "ask": 3.2, "volatility": 31.0, "openInterest": 5}]}}, "putExpDateMap": {}}
    _, sc = options.parse_schwab_chain(sraw)
    assert sc[0]["contract"] == "ZZZ261204C00102000" and abs(sc[0]["iv"] - 0.31) < 1e-9
    from floor import schwab
    q = schwab.parse_quotes({"AAPL": {"quote": {"lastPrice": 190.1, "quoteTime": 1700000000000, "netPercentChange": 1.2}}, "BAD": {}})
    assert q["AAPL"]["last"] == 190.1 and q["AAPL"]["time"] == 1700000000.0 and "BAD" not in q


class _RealOptDemo(DemoProvider):
    """Demo market, but options come from a (fixture) real chain and prices can be verified."""
    def __init__(self, *a, ref_bias=1.0, **k):
        super().__init__(*a, **k)
        self.ref_bias = ref_bias
        self.asked = []

    def option_chain(self, sym):
        # a stable ladder of strikes (like a real chain), so a held contract stays quotable as the stock moves
        base = self.series[sym][self.index[self.first_sim.isoformat()] - 1]["close"]
        out = []
        for i in range(25, 81):
            kk = round(base * i * 0.02 * 2) / 2
            for cp in ("call", "put"):
                out.append({"contract": f"{sym}261204{'C' if cp == 'call' else 'P'}{int(kk * 1000):08d}", "cp": cp, "strike": float(kk), "expiry": "2026-12-04",
                            "bid": 3.0, "ask": 3.2, "iv": 0.35, "delta": 0.45, "volume": 100, "oi": 500})
        return out, "cboe"

    def option_quote(self, sym, contract):
        for c in self.option_chain(sym)[0]:
            if c["contract"] == contract:
                return c
        return None

    def verify_price(self, sym, price):
        self.asked.append(sym)
        return {"ref": price * self.ref_bias, "src": "schwab"}


def _first_options_day(prov, fl, days=6):
    for d in [x for x in prov.days if x >= prov.first_sim][:days]:
        for m in (5, 65, 125, 185, 245, 305, 365):
            t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=clock.ET) + timedelta(minutes=m)
            prov.set_time(t)
            fl.run(t.astimezone(timezone.utc), log=lambda *_: None)


@test
def real_option_quotes_are_used_and_paid_at_the_ask():
    tmp = Path(tempfile.mkdtemp())
    try:
        prov = _RealOptDemo(sim_days=8)
        fl = Floor(prov, Store(tmp), demo=True)
        _first_options_day(prov, fl)
        opts = [o for a in fl.state["accounts"].values() for o in a["orders"] if o["kind"] != "stock" and o["side"] == "BUY"]
        assert opts, "expected at least one option purchase in six simulated days"
        for o in opts:
            assert o["src"] == "cboe" and o["fill"] == 3.2, "must pay the quoted ask, not a modeled price"
            assert o["option"]["contract"] and o["option"]["source"] == "cboe" and not o["option"]["model_priced"]
        sells = [o for a in fl.state["accounts"].values() for o in a["orders"] if o["kind"] != "stock" and o["side"] == "SELL"]
        assert all(o["fill"] == 3.0 for o in sells), "must sell at the quoted bid"
        assert prov.asked, "price verification was never consulted"
        for a in fl.state["accounts"].values():
            assert abs(_reconcile(a) - ledger.equity(a)) < 0.5
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def trade_refused_when_verified_price_disagrees():
    tmp = Path(tempfile.mkdtemp())
    try:
        prov = _RealOptDemo(sim_days=8, ref_bias=1.05)   # the independent feed says 5% higher: something is wrong
        fl = Floor(prov, Store(tmp), demo=True)
        _first_options_day(prov, fl)
        assert prov.asked
        assert all(len(a["orders"]) == 0 for a in fl.state["accounts"].values()), "no trade may happen on an unverified price"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def stale_quotes_are_never_traded_on():
    tmp = Path(tempfile.mkdtemp())
    try:
        prov = DemoProvider(sim_days=3)
        real = prov.intraday
        d = prov.first_sim
        now = datetime(d.year, d.month, d.day, 9, 30, tzinfo=clock.ET) + timedelta(minutes=125)
        prov.set_time(now)
        prov.intraday = lambda s: {**real(s), "asof": now.timestamp() - 3600} if real(s) else None   # one hour old
        fl = Floor(prov, Store(tmp), demo=True)
        res = fl.run(now.astimezone(timezone.utc), log=lambda *_: None)
        assert not res["changed"] and res["error"] == "stale quotes"
        prov.intraday = lambda s: {**real(s), "asof": now.timestamp() - 30} if real(s) else None    # 30 seconds old: fine
        assert fl.run(now.astimezone(timezone.utc), log=lambda *_: None)["changed"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def manage_run_updates_positions_but_never_opens_trades():
    tmp = Path(tempfile.mkdtemp())
    try:
        prov = DemoProvider(sim_days=6)
        fl = Floor(prov, Store(tmp), demo=True)
        d = prov.first_sim
        for day in [x for x in prov.days if x >= prov.first_sim][:4]:
            for m in (5, 65, 125):
                t = datetime(day.year, day.month, day.day, 9, 30, tzinfo=clock.ET) + timedelta(minutes=m)
                prov.set_time(t)
                fl.run(t.astimezone(timezone.utc), log=lambda *_: None)
        before = {a: len(v["orders"]) for a, v in fl.state["accounts"].items()}
        npos = sum(len(v["positions"]) for v in fl.state["accounts"].values())
        t = datetime(day.year, day.month, day.day, 9, 30, tzinfo=clock.ET) + timedelta(minutes=140)
        prov.set_time(t)
        res = fl.run(t.astimezone(timezone.utc), manage_only=True, log=lambda *_: None)
        assert res["changed"] and fl.info["mode"] == "manage"
        for a, v in fl.state["accounts"].items():
            assert all(o["side"] == "SELL" for o in v["orders"][before[a]:]), "a manage run may only sell"
        if npos:
            p = next(p for v in fl.state["accounts"].values() for p in v["positions"])
            assert len(p["track"]) >= 2, "positions must keep a price track"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ the LIVE code path against fake HTTP
def _yahoo_daily(bars):
    ts = [int(datetime.fromisoformat(b["date"] + "T14:30:00+00:00").timestamp()) for b in bars]
    q = {k: [b[k] for b in bars] for k in ("open", "high", "low", "close", "volume")}
    return {"chart": {"result": [{"meta": {}, "timestamp": ts, "indicators": {"quote": [q], "adjclose": [{"adjclose": [b["close"] for b in bars]}]}}], "error": None}}


def _yahoo_5m(sn):
    n = sn["n_bars"]
    p0, p1 = sn["open"], sn["price"]
    closes = [p0 + (p1 - p0) * (i + 1) / n for i in range(n)]
    q = {"open": [p0] + closes[:-1], "high": [max(a, b) * 1.0005 for a, b in zip([p0] + closes[:-1], closes)], "low": [min(a, b) * .9995 for a, b in zip([p0] + closes[:-1], closes)],
         "close": closes, "volume": [sn["volume"] / n] * n}
    return {"chart": {"result": [{"meta": {"regularMarketPrice": p1, "chartPreviousClose": sn["prev_close"], "regularMarketTime": 1, "marketState": "REGULAR"},
                                 "timestamp": list(range(n)), "indicators": {"quote": [q]}}]}}


@test
def live_path_against_fake_http():
    demo = DemoProvider(sim_days=2)
    d = demo.first_sim
    now = datetime(d.year, d.month, d.day, 11, 35, tzinfo=clock.ET)   # 125 minutes in
    demo.set_time(now)
    calls = {"n": 0}
    rss = b"<rss><channel><item><title>Stock surges after record profit beat</title><link>x</link><pubDate>%s</pubDate></item><item><title>Analyst upgrade lifts shares</title><pubDate>%s</pubDate></item></channel></rss>" % (
        datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT").encode(), datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT").encode())

    def fake(url, *a, **k):
        calls["n"] += 1
        if "wikipedia" in url:
            raise RuntimeError("blocked")
        if "range=1d&interval=5m" in url:
            sym = url.split("/chart/")[1].split("?")[0].replace("%5E", "^")
            sn = demo.intraday(sym)
            if not sn:
                raise RuntimeError("no data")
            return json.dumps(_yahoo_5m(sn)).encode()
        if "/v8/finance/chart/" in url:
            sym = url.split("/chart/")[1].split("?")[0].replace("%5E", "^")
            return json.dumps(_yahoo_daily(demo.daily(sym))).encode()
        if "fredgraph" in url:
            return b"DATE,X\n2026-10-29,4.0\n2026-10-30,4.1\n"
        if "fearandgreed" in url:
            return json.dumps({"fear_and_greed": {"score": 47.0, "rating": "neutral"}}).encode()
        if "nasdaq.com" in url:
            return json.dumps({"data": {"rows": [{"symbol": "AAPL"}]}}).encode()
        if "rss" in url or "news.google" in url:
            return rss
        raise RuntimeError("unexpected url " + url)

    tmp = Path(tempfile.mkdtemp())
    old = (sources.http_get, market_data._get)
    try:
        sources.http_get = fake
        market_data._get = fake
        live = LiveProvider(tmp)
        fl = Floor(live, Store(tmp))
        res = fl.run(now.astimezone(timezone.utc), log=lambda *_: None)
        assert res["changed"], res
        board = json.loads((tmp / "leaderboard.json").read_text())
        assert not board["demo"] and board["phase"] == "open"
        mk = json.loads((tmp / "market.json").read_text())
        names = {s["name"]: s["status"] for s in mk["sources"]}
        assert names["Fear & Greed index (CNN)"] == "ok" and names["Treasury yields & credit spreads (FRED)"] == "ok"
        assert mk["universe"]["source"] == "built-in list", "wikipedia was blocked, so it must fall back"
        assert mk["universe"]["with_features"] > 100
        assert mk["macro"]["fng"]["score"] == 47.0 and mk["macro"]["ten_year"] == 4.1
        assert (tmp / "features.json").exists()
    finally:
        sources.http_get, market_data._get = old
        shutil.rmtree(tmp, ignore_errors=True)


@test
def all_sources_down_changes_nothing():
    tmp = Path(tempfile.mkdtemp())
    old = (sources.http_get, market_data._get)
    try:
        def boom(*a, **k):
            raise RuntimeError("network down")
        sources.http_get = boom
        market_data._get = boom
        sources.time.sleep = lambda *_: None
        fl = Floor(LiveProvider(tmp), Store(tmp))
        res = fl.run(datetime(2026, 11, 2, 16, 35, tzinfo=timezone.utc), log=lambda *_: None)
        assert not res["changed"]
        assert not (tmp / "leaderboard.json").exists()
    finally:
        sources.http_get, market_data._get = old
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import time as _t
    sources.time.sleep = lambda *_: None
    market_data.time.sleep = lambda *_: None
    bad = 0
    for fn in TESTS:
        t0 = _t.time()
        try:
            fn()
            print(f"PASS {fn.__name__} ({_t.time() - t0:.1f}s)")
        except Exception:  # noqa: BLE001
            bad += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - bad}/{len(TESTS)} passed")
    sys.exit(1 if bad else 0)
