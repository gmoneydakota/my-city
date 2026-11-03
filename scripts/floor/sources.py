"""Public data sources. Every fetcher is defensive: one failing API never stops a run.

Live sources (all free, no key):
  Yahoo Finance chart API ... daily + 5-minute prices, VIX, indices, sector ETFs
  Stooq ..................... daily-price fallback
  FRED (fredgraph.csv) ...... treasury yields, high-yield credit spread
  CNN Fear & Greed .......... market sentiment gauge
  Google News RSS ........... headlines per ticker
  Yahoo Finance RSS ......... headlines per ticker (second opinion)
  Nasdaq earnings calendar .. who reports today / tomorrow
  Wikipedia ................. S&P 500 membership (cached weekly)
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from market_data import fetch_history  # noqa: E402  (daily bars, Yahoo then Stooq)

UA = "Mozilla/5.0 (X11; Linux x86_64) AgentCity-TradingFloor/1.0"


def http_get(url: str, timeout: int = 20, retries: int = 2, headers: dict | None = None) -> bytes:
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 * (i + 1))
    raise RuntimeError(f"{url.split('?')[0]}: {last}")


def http_post(url: str, data: bytes, headers: dict | None = None, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, data=data, method="POST", headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def pmap(fn, items, workers=8):
    """Parallel map that never raises: returns {item: result_or_None}."""
    out = {}

    def one(x):
        try:
            return x, fn(x)
        except Exception:  # noqa: BLE001
            return x, None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for k, v in ex.map(one, items):
            out[k] = v
    return out


# ---------------------------------------------------------------- prices

def parse_intraday(raw: dict, tz_offset_minutes: int | None = None) -> dict | None:
    """Yahoo chart (range=1d, interval=5m) -> snapshot used by the traders."""
    res = ((raw.get("chart") or {}).get("result") or [None])[0]
    if not res:
        return None
    meta = res.get("meta") or {}
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    ts = res.get("timestamp") or []
    bars = []
    for i, t in enumerate(ts):
        c = (q.get("close") or [None] * len(ts))[i]
        if c is None:
            continue
        bars.append({"t": t, "o": q["open"][i] or c, "h": q["high"][i] or c, "l": q["low"][i] or c, "c": c, "v": q["volume"][i] or 0})
    price = meta.get("regularMarketPrice") or (bars[-1]["c"] if bars else None)
    if not price:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    vol = sum(b["v"] for b in bars)
    pv = sum(((b["h"] + b["l"] + b["c"]) / 3) * b["v"] for b in bars)
    first = bars[:6]  # first 30 minutes = opening range
    return {
        "price": float(price), "prev_close": float(prev) if prev else None,
        "open": bars[0]["o"] if bars else float(price),
        "high": max((b["h"] for b in bars), default=float(price)), "low": min((b["l"] for b in bars), default=float(price)),
        "volume": vol, "vwap": (pv / vol) if vol else float(price),
        "or_high": max((b["h"] for b in first), default=None), "or_low": min((b["l"] for b in first), default=None),
        "n_bars": len(bars), "asof": meta.get("regularMarketTime") or (bars[-1]["t"] if bars else None),
        "state": meta.get("marketState"),
    }


def yahoo_intraday(symbol: str) -> dict | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=5m&includePrePost=false"
    return parse_intraday(json.loads(http_get(url, timeout=15, retries=1)))


def daily_bars(symbol: str, years: int = 1) -> list[dict]:
    return fetch_history(symbol, years)


# ---------------------------------------------------------------- universe

FALLBACK_UNIVERSE = (
    "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO LLY JPM V UNH XOM MA COST HD PG JNJ ORCL NFLX ABBV BAC CRM CVX KO WMT MRK "
    "AMD PEP TMO ADBE LIN ACN MCD CSCO ABT WFC DHR TXN QCOM GE IBM INTU CAT VZ AMGN ISRG NOW PFE DIS SPGI UBER GS MS "
    "AXP RTX NEE HON LOW T BKNG PGR UNP AMAT ETN BA SYK TJX COP LMT ELV PLD VRTX BLK SCHW MDT C ADP MU PANW GILD "
    "ADI LRCX KLAC SBUX DE MMC CB FI CI BX REGN SO MO ZTS NKE SHOP PYPL ABNB COIN PLTR SNOW CRWD DDOG MRVL ANET "
    "SMCI ARM MSTR HOOD SOFI RIVN F GM INTC DAL UAL CCL AAL XLF XLE XLK XLV XLY XLP XLI XLU XLB XLRE XLC SMH IWM GLD TLT"
).split()

SECTORS = {"XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care", "XLY": "Consumer Disc.",
           "XLP": "Consumer Staples", "XLI": "Industrials", "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate",
           "XLC": "Communication"}
INDEXES = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "DIA": "Dow", "^VIX": "VIX", "^TNX": "10Y yield",
           "GLD": "Gold", "TLT": "20Y+ Treasuries", "UUP": "US Dollar"}


def parse_sp500(html: str) -> list[str]:
    """S&P 500 tickers from the Wikipedia constituents table."""
    m = re.search(r'id="constituents".*?</table>', html, re.S)
    chunk = m.group(0) if m else html
    syms = re.findall(r'<td><a[^>]*class="external text"[^>]*>([A-Z][A-Z.\-]{0,5})</a>', chunk)
    seen, out = set(), []
    for s in syms:
        s = s.replace(".", "-")
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def load_universe(cache: Path, max_age_days: int = 7) -> tuple[list[str], str]:
    try:
        d = json.loads(cache.read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(d["fetched"])).days
        if age < max_age_days and len(d["symbols"]) > 100:
            return d["symbols"], "cache"
    except Exception:  # noqa: BLE001
        pass
    try:
        html = http_get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", timeout=25).decode("utf8", "ignore")
        syms = parse_sp500(html)
        if len(syms) >= 400:
            extra = [s for s in FALLBACK_UNIVERSE if s not in syms]
            syms = syms + extra
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "symbols": syms}))
            return syms, "wikipedia"
    except Exception:  # noqa: BLE001
        pass
    return list(dict.fromkeys(FALLBACK_UNIVERSE)), "built-in list"


# ---------------------------------------------------------------- macro

def parse_fred_csv(text: str) -> tuple[float | None, float | None]:
    """Last two numeric observations -> (latest, previous)."""
    vals = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[1] not in ("", ".", "VALUE") and re.match(r"^-?\d", row[1]):
            try:
                vals.append(float(row[1]))
            except ValueError:
                pass
    if not vals:
        return None, None
    return vals[-1], vals[-2] if len(vals) > 1 else None


def fred(series: str):
    return parse_fred_csv(http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=20).decode())


def parse_fear_greed(raw: dict) -> dict | None:
    fg = raw.get("fear_and_greed") or {}
    if "score" not in fg:
        return None
    return {"score": round(float(fg["score"]), 1), "rating": str(fg.get("rating", "")), "previous_close": fg.get("previous_close")}


def fear_greed() -> dict | None:
    raw = json.loads(http_get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", timeout=15, retries=1,
                              headers={"Referer": "https://www.cnn.com/", "Origin": "https://www.cnn.com"}))
    return parse_fear_greed(raw)


def parse_earnings(raw: dict) -> set[str]:
    rows = ((raw.get("data") or {}).get("rows")) or []
    return {r["symbol"].replace(".", "-") for r in rows if r.get("symbol")}


def earnings_on(day: str) -> set[str]:
    raw = json.loads(http_get(f"https://api.nasdaq.com/api/calendar/earnings?date={day}", timeout=15, retries=1,
                              headers={"Accept": "application/json"}))
    return parse_earnings(raw)


def cboe_chain(symbol: str):
    """Free, ~15-minute-delayed option chain with real bid/ask/IV from CBOE."""
    from .options import parse_cboe
    raw = json.loads(http_get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{urllib.parse.quote(symbol)}.json", timeout=20, retries=1))
    return parse_cboe(raw)


# ---------------------------------------------------------------- news

POS = set("""beat beats surge surges soar soars jump jumps rally rallies upgrade upgraded raises raised record strong growth
profit gains gain bullish outperform buy approval approved wins win breakthrough expands expansion boost boosts tops topped
higher rises rise climbs climb optimistic accelerates partnership contract""".split())
NEG = set("""miss misses plunge plunges slump slumps drop drops fall falls downgrade downgraded cuts cut lawsuit probe investigation
recall weak loss losses bearish underperform sell warning warns layoffs layoff fraud delay delays halts halt bankruptcy lower
sinks sink tumbles tumble concern concerns fears fear decline declines slows slowdown tariff tariffs resigns""".split())


def sentiment(titles: list[str]) -> float:
    """Lexicon score in [-1, 1]: (pos - neg) / (pos + neg + 2)."""
    p = n = 0
    for t in titles:
        for w in re.findall(r"[a-z']+", t.lower()):
            p += w in POS
            n += w in NEG
    return round((p - n) / (p + n + 2), 3)


def parse_rss(xml_bytes: bytes, limit: int = 12, max_age_hours: float = 72) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    now = datetime.now(timezone.utc)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        when = None
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "")
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            pass
        if when and (now - when).total_seconds() > max_age_hours * 3600:
            continue
        src = it.findtext("source") or ""
        out.append({"title": title, "link": (it.findtext("link") or "").strip(), "source": src,
                    "time": when.isoformat() if when else None})
        if len(out) >= limit:
            break
    return out


def news(symbol: str) -> list[dict]:
    items: list[dict] = []
    try:
        q = urllib.parse.quote(f"{symbol} stock when:2d")
        items += parse_rss(http_get(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en", timeout=12, retries=1))
    except Exception:  # noqa: BLE001
        pass
    try:
        items += parse_rss(http_get(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(symbol)}&region=US&lang=en-US", timeout=12, retries=1))
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for i in items:
        k = re.sub(r"\W+", "", i["title"].lower())[:60]
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out[:14]


def market_news() -> list[dict]:
    q = urllib.parse.quote("stock market OR Wall Street OR Federal Reserve when:1d")
    return parse_rss(http_get(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en", timeout=12, retries=1), limit=15)
