"""The Odds API (https://the-odds-api.com) – optional, needs a free key in ODDS_API_KEY.

Adds: multi-book consensus for game lines (sharper "fair" price than DK alone),
DraftKings player-prop prices, and Underdog pick'em prop lines.
Free tier = 500 credits/month. Cost here: 3 credits per slate for game lines and
roughly (#prop markets) credits per event for props. Use --max-events to budget.
"""
from __future__ import annotations

from .common import DataError, get_json

BASE = "https://api.the-odds-api.com/v4"
SPORT = {"nba": "basketball_nba", "nfl": "americanfootball_nfl"}

# Sportsbooks used for the consensus "fair" price (DFS apps excluded from consensus).
# 9 books + Underdog = 10 bookmakers = billed as ONE region (5 credits per game for 5 prop markets)
CONSENSUS_BOOKS = ["draftkings", "fanduel", "betmgm", "williamhill_us", "espnbet", "betrivers", "fanatics",
                   "pinnacle", "betonlineag"]
DFS_BOOKS = ["underdog"]

PROP_MARKETS = {
    "nba": {
        "player_points": "points", "player_rebounds": "rebounds", "player_assists": "assists",
        "player_threes": "threes", "player_points_rebounds_assists": "pra",
        "player_points_rebounds": "pr", "player_points_assists": "pa", "player_rebounds_assists": "ra",
        "player_blocks": "blocks", "player_steals": "steals", "player_turnovers": "turnovers",
    },
    "nfl": {
        "player_pass_yds": "pass_yds", "player_pass_tds": "pass_tds", "player_pass_completions": "completions",
        "player_pass_attempts": "pass_att", "player_pass_interceptions": "interceptions",
        "player_rush_yds": "rush_yds", "player_rush_attempts": "rush_att", "player_receptions": "receptions",
        "player_reception_yds": "rec_yds", "player_rush_reception_yds": "rush_rec_yds",
        "player_anytime_td": "anytime_td",
    },
}
DEFAULT_PROP_MARKETS = {
    "nba": ["player_points", "player_rebounds", "player_assists", "player_threes", "player_points_rebounds_assists"],
    "nfl": ["player_pass_yds", "player_rush_yds", "player_reception_yds", "player_receptions", "player_anytime_td"],
}

def _get(path: str, key: str, params: dict, ttl: float):
    p = dict(params)
    p["apiKey"] = key
    return get_json(f"{BASE}{path}", p, ttl_hours=ttl)


def nickname(team_name: str) -> str:
    """'Los Angeles Clippers' / 'LA Clippers' -> 'clippers' (used to match ESPN to Odds API)."""
    return team_name.lower().split()[-1] if team_name else ""


def game_lines(league: str, key: str) -> dict[tuple[str, str], dict]:
    """(home_nick, away_nick) -> {book: {ml_home, ml_away, spread_home, spread_home_odds,...}}."""
    data = _get(f"/sports/{SPORT[league]}/odds", key,
                {"regions": "us,us2,eu", "markets": "h2h,spreads,totals", "oddsFormat": "american"}, ttl=0.5)
    out = {}
    for ev in data:
        hn, an = nickname(ev["home_team"]), nickname(ev["away_team"])
        books = {}
        for b in ev.get("bookmakers", []):
            row = {}
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    side = "home" if o["name"] == ev["home_team"] else "away" if o["name"] == ev["away_team"] else None
                    if m["key"] == "h2h" and side:
                        row[f"ml_{side}"] = o["price"]
                    elif m["key"] == "spreads" and side:
                        row[f"spread_{side}"] = o.get("point")
                        row[f"spread_{side}_odds"] = o["price"]
                    elif m["key"] == "totals":
                        if o["name"] == "Over":
                            row["total"], row["over_odds"] = o.get("point"), o["price"]
                        elif o["name"] == "Under":
                            row["under_total"], row["under_odds"] = o.get("point"), o["price"]
            books[b["key"]] = row
        out[(hn, an)] = {"books": books, "id": ev["id"], "commence": ev["commence_time"]}
    return out


def events(league: str, key: str) -> list[dict]:
    """Upcoming events (free endpoint, no credits)."""
    return _get(f"/sports/{SPORT[league]}/events", key, {}, ttl=1)


def event_props(league: str, key: str, event_id: str, markets: list[str]) -> list[dict]:
    """Flat list of prop quotes: {player, stat, line, side('over'/'under'), price, book}."""
    books = ",".join(CONSENSUS_BOOKS + DFS_BOOKS)
    try:
        data = _get(f"/sports/{SPORT[league]}/events/{event_id}/odds", key,
                    {"bookmakers": books, "markets": ",".join(markets), "oddsFormat": "american"}, ttl=0.5)
    except DataError:
        return []
    quotes = []
    mapping = PROP_MARKETS[league]
    for b in data.get("bookmakers", []):
        for m in b.get("markets", []):
            stat = mapping.get(m["key"])
            if not stat:
                continue
            for o in m.get("outcomes", []):
                name = (o.get("name") or "").lower()
                player = o.get("description") or ""
                if not player:
                    continue
                if stat == "anytime_td":
                    side, line = ("over" if name in ("yes", "over") else "under"), 0.5
                else:
                    side = "over" if name == "over" else "under" if name == "under" else None
                    line = o.get("point")
                if side is None or line is None:
                    continue
                quotes.append({"player": player, "stat": stat, "line": float(line), "side": side,
                               "price": o.get("price"), "book": b["key"]})
    return quotes


# --------------------------------------------------------------------------- credit budget
# The free Odds API plan has ~500 credits/month. Spread them evenly over the month (unused credits
# roll forward), never go over, and reuse the morning's prop lines for later runs the same day.
import os as _os
from datetime import datetime as _dt, timezone as _tz
import calendar as _cal
import json as _json
from .common import ROOT as _ROOT

USAGE = _ROOT / "history" / "odds_usage.json"
MONTHLY_BUDGET = int(_os.environ.get("ODDS_MONTHLY_BUDGET", "480"))


def _usage() -> dict:
    month = _dt.now(_tz.utc).strftime("%Y-%m")
    try:
        u = _json.loads(USAGE.read_text())
    except Exception:  # noqa: BLE001
        u = {}
    if u.get("month") != month:
        u = {"month": month, "used": 0, "days": {}}
    return u


def allowance() -> int:
    """Credits we may still spend today (even share of what's left this month)."""
    u, now = _usage(), _dt.now(_tz.utc)
    days_left = _cal.monthrange(now.year, now.month)[1] - now.day + 1
    left = MONTHLY_BUDGET - u["used"]
    spent_today = u["days"].get(now.strftime("%d"), 0)
    per_day = (left + spent_today) / days_left
    return max(0, int(per_day - spent_today))


def spend(credits: int) -> None:
    u, now = _usage(), _dt.now(_tz.utc)
    u["used"] += credits
    d = now.strftime("%d")
    u["days"][d] = u["days"].get(d, 0) + credits
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    USAGE.write_text(_json.dumps(u, indent=1))


def prop_cost(markets: list[str]) -> int:
    regions = -(-len(CONSENSUS_BOOKS + DFS_BOOKS) // 10)
    return len(markets) * regions


QUOTES = _ROOT / "history" / "prop_quotes"


def save_quotes(league: str, quotes: list[dict]) -> None:
    QUOTES.mkdir(parents=True, exist_ok=True)
    (QUOTES / f"{league}.json").write_text(_json.dumps({"fetched_at": _dt.now(_tz.utc).isoformat(timespec="seconds"),
                                                        "quotes": quotes}))


def load_quotes(league: str, max_age_hours: float = 20) -> tuple[list[dict], str | None]:
    try:
        d = _json.loads((QUOTES / f"{league}.json").read_text())
        age = (_dt.now(_tz.utc) - _dt.fromisoformat(d["fetched_at"])).total_seconds() / 3600
        return (d["quotes"], d["fetched_at"]) if age <= max_age_hours else ([], None)
    except Exception:  # noqa: BLE001
        return [], None
