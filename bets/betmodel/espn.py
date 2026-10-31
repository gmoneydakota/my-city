"""ESPN public JSON endpoints (no key): schedules, results, DraftKings lines,
injuries, rosters and player game logs."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from .common import DataError, get_json, parse_american

SITE = "https://site.api.espn.com/apis/site/v2/sports"
WEB = "https://site.web.api.espn.com/apis/common/v3/sports"

LEAGUES = {
    "nba": {"path": "basketball/nba"},
    "nfl": {"path": "football/nfl"},
}


def _path(league: str) -> str:
    try:
        return LEAGUES[league]["path"]
    except KeyError:
        raise ValueError(f"unknown league {league!r}; use nba or nfl") from None


def parse_time(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    if re.match(r".*T\d\d:\d\d\+", s):  # '2026-11-01T18:00+00:00' (no seconds)
        s = s.replace("+", ":00+", 1)
    return datetime.fromisoformat(s)


def norm_name(name: str) -> str:
    """'Shai Gilgeous-Alexander Jr.' -> 'shai gilgeous alexander'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`]", "", s)
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", s)
    return " ".join(s.split())


def _score(c) -> float | None:
    sc = c.get("score")
    if isinstance(sc, dict):
        sc = sc.get("value", sc.get("displayValue"))
    try:
        return float(sc)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- teams / schedule
def current_season(league: str) -> int:
    d = get_json(f"{SITE}/{_path(league)}/scoreboard", ttl_hours=6)
    return int(d["season"]["year"])


def teams(league: str) -> dict[str, dict]:
    d = get_json(f"{SITE}/{_path(league)}/teams", ttl_hours=72)
    out = {}
    for t in d["sports"][0]["leagues"][0]["teams"]:
        t = t["team"]
        out[t["id"]] = {"id": t["id"], "abbr": t["abbreviation"], "name": t["displayName"]}
    return out


def team_schedule(league: str, team_id: str, season: int) -> list[dict]:
    """All regular-season games (played and upcoming) for one team."""
    d = get_json(f"{SITE}/{_path(league)}/teams/{team_id}/schedule",
                 {"season": season, "seasontype": 2}, ttl_hours=6)
    games = []
    for e in d.get("events", []):
        comp = e["competitions"][0]
        home = next((c for c in comp["competitors"] if c["homeAway"] == "home"), None)
        away = next((c for c in comp["competitors"] if c["homeAway"] == "away"), None)
        if not home or not away:
            continue
        status = (comp.get("status") or e.get("status") or {}).get("type", {})
        games.append({
            "event_id": e["id"],
            "date": parse_time(e["date"]),
            "home": home["team"]["id"] if "team" in home else home["id"],
            "away": away["team"]["id"] if "team" in away else away["id"],
            "home_score": _score(home),
            "away_score": _score(away),
            "final": bool(status.get("completed")),
            "neutral": bool(comp.get("neutralSite")),
        })
    return games


def league_games(league: str, season: int) -> list[dict]:
    """Every regular-season game for a season, de-duplicated across team schedules."""
    seen = {}
    for tid in teams(league):
        try:
            for g in team_schedule(league, tid, season):
                seen[g["event_id"]] = g
        except DataError:
            continue
    return sorted(seen.values(), key=lambda g: g["date"])


# --------------------------------------------------------------------------- slate + DK lines
def _odds_side(block: dict | None, side: str) -> tuple[float | None, float | None]:
    """(line, american price) from ESPN's odds block; prefers current ('close') over open."""
    s = (block or {}).get(side) or {}
    node = s.get("close") or s.get("current") or s.get("open") or {}
    line = node.get("line")
    if isinstance(line, str):
        line = line.lstrip("ou")
        try:
            line = float(line)
        except ValueError:
            line = None
    return line, parse_american(node.get("odds"))


def slate(league: str, date: str | None = None) -> list[dict]:
    """Upcoming games on the ESPN scoreboard with DraftKings odds when posted.

    date: 'YYYYMMDD' (NBA: that day; NFL: the week containing it). None = today/this week.
    """
    params = {"dates": date} if date else None
    d = get_json(f"{SITE}/{_path(league)}/scoreboard", params, ttl_hours=0.25)
    out = []
    for e in d.get("events", []):
        comp = e["competitions"][0]
        st = comp["status"]["type"]
        home = next(c for c in comp["competitors"] if c["homeAway"] == "home")
        away = next(c for c in comp["competitors"] if c["homeAway"] == "away")
        g = {
            "event_id": e["id"], "date": parse_time(e["date"]), "name": e.get("shortName", e["name"]),
            "state": st.get("state"), "completed": bool(st.get("completed")),
            "home": home["team"]["id"], "away": away["team"]["id"],
            "home_abbr": home["team"]["abbreviation"], "away_abbr": away["team"]["abbreviation"],
            "neutral": bool(comp.get("neutralSite")),
            "home_score": _score(home), "away_score": _score(away),
            "dk": None,
        }
        for o in comp.get("odds") or []:
            prov = (o.get("provider") or {}).get("name", "")
            if "draft" not in prov.lower():
                continue
            ml = o.get("moneyline") or {}
            ps = o.get("pointSpread") or {}
            tot = o.get("total") or {}
            dk = {
                "ml_home": _odds_side(ml, "home")[1], "ml_away": _odds_side(ml, "away")[1],
                "spread_home": _odds_side(ps, "home")[0], "spread_home_odds": _odds_side(ps, "home")[1],
                "spread_away": _odds_side(ps, "away")[0], "spread_away_odds": _odds_side(ps, "away")[1],
                "total": _odds_side(tot, "over")[0] or o.get("overUnder"),
                "over_odds": _odds_side(tot, "over")[1], "under_odds": _odds_side(tot, "under")[1],
            }
            if dk["spread_home"] is None and dk["spread_away"] is not None:
                dk["spread_home"] = -dk["spread_away"]
            if dk["spread_away"] is None and dk["spread_home"] is not None:
                dk["spread_away"] = -dk["spread_home"]
            g["dk"] = dk
            break
        out.append(g)
    return out


# --------------------------------------------------------------------------- injuries / rosters
def injuries(league: str) -> dict[str, dict]:
    """norm_name -> {'name', 'status', 'team', 'detail'} for everyone on ESPN's injury report."""
    try:
        d = get_json(f"{SITE}/{_path(league)}/injuries", ttl_hours=1)
    except DataError:
        return {}
    out = {}
    for team in d.get("injuries", []):
        for i in team.get("injuries", []):
            a = i.get("athlete") or {}
            name = a.get("displayName") or f"{a.get('firstName', '')} {a.get('lastName', '')}".strip()
            if not name or i.get("status", "").lower() == "active":
                continue
            out[norm_name(name)] = {
                "name": name, "status": i.get("status", "?"), "team": team.get("displayName", ""),
                "detail": i.get("shortComment", "")[:140],
            }
    return out


def roster(league: str, team_id: str) -> list[dict]:
    d = get_json(f"{SITE}/{_path(league)}/teams/{team_id}/roster", ttl_hours=24)
    out = []
    for a in d.get("athletes", []):
        items = a.get("items") if isinstance(a, dict) and "items" in a else [a]  # NFL groups by unit
        for p in items:
            out.append({"id": p["id"], "name": p.get("displayName") or p.get("fullName", ""),
                        "pos": (p.get("position") or {}).get("abbreviation", ""), "team_id": team_id})
    return out


# --------------------------------------------------------------------------- game logs
def gamelog(league: str, athlete_id: str, season: int | None = None) -> list[dict]:
    """Regular-season games for a player, newest first: [{'event_id','date','opp', stat: value}]."""
    params = {"season": season} if season else None
    try:
        d = get_json(f"{WEB}/{_path(league)}/athletes/{athlete_id}/gamelog", params, ttl_hours=6)
    except DataError:
        return []
    names = d.get("names") or []
    meta = d.get("events") or {}
    rows = []
    for st in d.get("seasonTypes", []):
        label = st.get("displayName", "")
        if "Regular" not in label:
            continue
        for cat in st.get("categories", []):
            for ev in cat.get("events", []):
                stats = ev.get("stats") or []
                m = meta.get(ev.get("eventId"), {})
                row = {"event_id": ev.get("eventId"),
                       "date": parse_time(m["gameDate"]) if m.get("gameDate") else None,
                       "opp": (m.get("opponent") or {}).get("abbreviation", "")}
                for n, v in zip(names, stats):
                    if "-" in n and isinstance(v, str) and "-" in v:  # 'made-attempted'
                        made_name, att_name = n.split("-", 1)
                        try:
                            mv, av = v.split("-", 1)
                            row[made_name], row[att_name] = float(mv), float(av)
                        except ValueError:
                            pass
                        continue
                    try:
                        row[n] = float(str(v).replace(",", ""))
                    except ValueError:
                        pass
                rows.append(row)
    rows.sort(key=lambda r: r["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows
