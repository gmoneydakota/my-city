"""Turn the injury report into point-spread adjustments.

NBA: each missing player costs his team (Game Score - replacement level) * 0.45
points, where replacement level ~= 0.20 Game Score per minute played. Scaled by
how often he actually played recently (if he's been out all season, the team
ratings already reflect it). Day-to-day players count 30%.
NFL: only the starting QB is priced (≈ 5 points); other positions are left to
the market, which moves on them anyway.
"""
from __future__ import annotations

from . import availability, espn

STATUS_WEIGHT = {"out": 1.0, "doubtful": 0.85, "injured reserve": 1.0, "ir": 1.0, "suspension": 1.0,
                 "questionable": 0.4, "day-to-day": 0.3}
NBA_K = 0.45
NBA_REPLACEMENT_PER_MIN = 0.20
NBA_TEAM_CAP = 12.0
NFL_QB_VALUE = 5.0


def _game_score(r: dict) -> float:
    g = lambda k: r.get(k) or 0.0  # noqa: E731
    return (g("points") + 0.4 * g("fieldGoalsMade") - 0.7 * g("fieldGoalsAttempted")
            - 0.4 * (g("freeThrowsAttempted") - g("freeThrowsMade")) + 0.4 * g("totalRebounds")
            + g("steals") + 0.7 * g("assists") + 0.7 * g("blocks") - 0.4 * g("fouls") - g("turnovers"))


def team_adjustments(league: str, games: list[dict], inj: dict, pbook, model) -> tuple[dict, dict]:
    """Returns ({team_id: points (negative = weaker)}, {team_id: [descriptions]})."""
    team_ids = {t for g in games for t in (g["home"], g["away"])}
    tm = espn.teams(league)
    name_to_tid = {tm[t]["name"]: t for t in team_ids if t in tm}
    hits = []
    for nn, v in inj.items():
        w = STATUS_WEIGHT.get(v["status"].lower(), 0.0)
        tid = name_to_tid.get(v["team"])
        if not w or not tid:
            continue
        p = pbook.by_name.get(nn) or pbook.find(v["name"])
        if p and p["team_id"] == tid:
            hits.append((tid, p, w, v["status"]))
    pbook.prefetch([p["id"] for _, p, _, _ in hits])
    adj, desc = {}, {}
    team_games_played = {}
    for tid in team_ids:
        team_games_played[tid] = sum(1 for g in model.schedule if g["final"] and tid in (g["home"], g["away"]))
    if league == "nfl":
        starters = {}
        for tid in team_ids:
            qbs = [p for p in pbook.by_name.values() if p["team_id"] == tid and p["pos"] == "QB"]
            pbook.prefetch([q["id"] for q in qbs], full=False)
            best = max(qbs, key=lambda q: sum(r.get("passingAttempts") or 0 for r in (pbook.cur.get(q["id"]) or [])[:4]),
                       default=None)
            if best:
                starters[tid] = best["id"]
    for tid, p, w, status in hits:
        cur = pbook.cur.get(p["id"]) or []
        recent_team = max(1, min(10, team_games_played.get(tid, 0)))
        cutoff = sorted([g["date"] for g in model.schedule if g["final"] and tid in (g["home"], g["away"])])[-recent_team:]
        played_recent = sum(1 for r in cur if r.get("date") and cutoff and r["date"] >= cutoff[0])
        share = min(1.0, played_recent / recent_team) if cutoff else 0.0
        if league == "nba":
            rows = (pbook.logs.get(p["id"]) or cur)[:20]
            if not rows:
                continue
            gs = sum(_game_score(r) for r in rows) / len(rows)
            mins = sum(r.get("minutes") or 0 for r in rows) / len(rows)
            value = max(0.0, gs - NBA_REPLACEMENT_PER_MIN * mins) * NBA_K
        else:
            if starters.get(tid) != p["id"]:
                continue
            value = NFL_QB_VALUE
        pts = value * w * share
        if pts >= 0.3:
            adj[tid] = adj.get(tid, 0.0) - pts
            desc.setdefault(tid, []).append(f"{p['name']} {status} (-{pts:.1f})")
    if league == "nba":
        adj = {t: max(-NBA_TEAM_CAP, v) for t, v in adj.items()}
    return adj, desc


RETURN_WEIGHT = {"nba": 0.5, "nfl": 0.7}


def returning_adjustments(league: str, games: list[dict], inj: dict, pbook, model, avail) -> tuple[dict, dict]:
    """The mirror image of team_adjustments: a player who is BACK (not on the report, just missed team games
    or has played <=3 games since a layoff) lifts his team, because the ratings were fitted on games he sat
    out. Worth `RETURN_WEIGHT` of his full value. Returns ({team_id: points (positive = stronger)}, {team_id: [desc]})."""
    from . import props
    adj, desc = {}, {}
    for tid in {t for g in games for t in (g["home"], g["away"])}:
        for p in props.key_players(league, pbook, tid, 8):
            v = inj.get(espn.norm_name(p["name"]))
            if v and v["status"].lower() in (set(STATUS_WEIGHT) | {"suspension"}):
                continue   # still on the report: handled by team_adjustments / held back as uncertain
            if league == "nfl" and p["pos"] != "QB":
                continue
            st = avail.status(p)
            if not st["returning"]:
                continue
            if league == "nba":
                pbook.prefetch([p["id"]])
                rows = (pbook.logs.get(p["id"]) or pbook.cur.get(p["id"]) or [])[:20]
                if not rows:
                    continue
                gs = sum(_game_score(r) for r in rows) / len(rows)
                mins = sum(r.get("minutes") or 0 for r in rows) / len(rows)
                value = max(0.0, gs - NBA_REPLACEMENT_PER_MIN * mins) * NBA_K
            else:
                value = NFL_QB_VALUE
            # minutes limits shave part of the benefit on the first games back
            value *= 1 - availability.return_haircut(league, st)
            pts = value * RETURN_WEIGHT[league]
            if pts >= 0.3:
                adj[tid] = adj.get(tid, 0.0) + pts
                desc.setdefault(tid, []).append(f"{p['name']} back from injury (+{pts:.1f})")
        if league == "nba" and tid in adj:
            adj[tid] = min(NBA_TEAM_CAP / 2, adj[tid])
    return adj, desc
