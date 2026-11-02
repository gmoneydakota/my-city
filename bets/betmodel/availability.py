"""Who is actually going to play, and how much: injury status + players coming back.

Three things the plain game-log projection cannot see:

1. UNCERTAIN players (questionable / day-to-day). A prop on someone who may not suit up is a coin flip on
   whether the bet even has action, so these are held off the card (they still show in the projection sheet
   with their status).
2. RETURNING players. After a layoff the game log is stale and minutes/snaps are usually limited:
   - back today after missing games  -> project fewer minutes/snaps and a wider spread
   - back for 1-3 games              -> a smaller version of the same haircut
   The haircut grows with the length of the layoff.
3. TEAMMATES of a missing star. When a high-usage player is OUT, the others pick up his minutes/shots, but
   the recent log only shows that if he has already been out for a while. We add a small, capped bump for
   the part not already in the log.

Everything here is a deliberately modest heuristic; the weekly learner (learn.py) re-calibrates the
projections that come out the other end.
"""
from __future__ import annotations

from . import espn

UNCERTAIN = {"questionable", "day-to-day"}
OUT = {"out", "doubtful", "injured reserve", "ir", "suspension"}

MIN_GAP = {"nba": 3, "nfl": 2}            # consecutive team games missed that count as an injury layoff
RETURN_WINDOW = 3                          # games after coming back that still count as "returning"
# minutes/snaps cut on the first game back = BASE + PER_GAME * games missed, capped; fades over RETURN_WINDOW games
BASE_HAIRCUT = {"nba": 0.05, "nfl": 0.03}
PER_GAME_HAIRCUT = {"nba": 0.01, "nfl": 0.01}
MAX_HAIRCUT = {"nba": 0.20, "nfl": 0.12}
SD_WIDEN = 1.15                            # extra uncertainty around a returning player
TEAMMATE_BUMP_PER_MIN = 0.0035             # NBA: +0.35% per missing-minute of a star, capped
TEAMMATE_BUMP_CAP = 0.10


def team_game_ids(model, team_id: str) -> list[str]:
    """Event ids of the team's finished games, newest first."""
    gs = [g for g in model.schedule if g.get("final") and team_id in (g["home"], g["away"])]
    gs.sort(key=lambda g: g["date"], reverse=True)
    return [g["event_id"] for g in gs]


def player_status(rows: list[dict], team_ids: list[str], league: str) -> dict:
    """From a player's current-season log (newest first, only games he played) and the team's finished
    games (newest first): how many team games he has missed lately and whether he just came back.

    Returns {'missed_now', 'since_return', 'last_gap', 'returning'}.
      missed_now   team games since his last appearance (>0 and he's not on the report -> back today)
      since_return games he has played since the end of his most recent layoff (None if no layoff)
      last_gap     length of that layoff
    """
    played = {r.get("event_id") for r in rows if r.get("event_id")}
    if not rows or not team_ids:
        return {"missed_now": 0, "since_return": None, "last_gap": 0, "returning": False}
    min_gap = MIN_GAP[league]
    # walk the team's games newest -> oldest as a play/miss string
    seq = [gid in played for gid in team_ids]
    missed_now = 0
    while missed_now < len(seq) and not seq[missed_now]:
        missed_now += 1
    # most recent layoff that has already ended
    i = missed_now
    since_return = last_gap = None
    streak_played = 0
    while i < len(seq):
        if seq[i]:
            streak_played += 1
            i += 1
            continue
        gap = 0
        while i < len(seq) and not seq[i]:
            gap += 1
            i += 1
        if gap >= min_gap and i < len(seq):   # only a real layoff if he played before it too
            since_return, last_gap = streak_played, gap
            break
        streak_played += gap                   # short absence (rest day, one-gamer): not a layoff
    if missed_now >= len(seq):                 # no appearances with this team at all (traded / new): not a return
        return {"missed_now": 0, "since_return": None, "last_gap": 0, "returning": False}
    returning = (missed_now >= min_gap) or (since_return is not None and since_return <= RETURN_WINDOW)
    # missed_now >= min_gap but not on the injury report means he is back (or about to be) today
    return {"missed_now": missed_now, "since_return": since_return, "last_gap": last_gap or 0,
            "returning": returning}


def return_haircut(league: str, st: dict) -> float:
    """Fraction to cut from his projected minutes/snaps (0 = none)."""
    if st["missed_now"] >= MIN_GAP[league]:
        gap, k = st["missed_now"], 0          # first game back after `missed_now` games out
    elif st["since_return"] is not None and st["since_return"] <= RETURN_WINDOW:
        gap, k = st["last_gap"], st["since_return"]
    else:
        return 0.0
    cut = min(MAX_HAIRCUT[league], BASE_HAIRCUT[league] + PER_GAME_HAIRCUT[league] * gap)
    return cut * (1 - k / (RETURN_WINDOW + 1))  # fades as games pile up


def describe(league: str, st: dict) -> str:
    if st["missed_now"] >= MIN_GAP[league]:
        return f"returning from injury (missed last {st['missed_now']} team games)"
    if st["since_return"] is not None and st["since_return"] <= RETURN_WINDOW:
        n = st["since_return"]
        return f"{n} game{'s' if n != 1 else ''} back from a {st['last_gap']}-game absence"
    return ""


def adjust_projection(league: str, proj: dict | None, st: dict | None, teammate_bump: float = 0.0) -> dict | None:
    """Apply the returning-player haircut and teammate bump to a projection dict (returns a new dict)."""
    if not proj:
        return proj
    out = dict(proj)
    note = ""
    factor = 1.0
    if st and st.get("returning"):
        cut = return_haircut(league, st)
        if cut > 0:
            factor *= 1 - cut
            out["sd"] = out["sd"] * SD_WIDEN
            note = describe(league, st)
    if teammate_bump:
        factor *= 1 + teammate_bump
        note = (note + "; " if note else "") + f"+{teammate_bump:.0%} with teammates out"
    out["mean"] = out["mean"] * factor
    out["sd"] = out["sd"] * (factor ** 0.5)
    if note:
        out["avail_note"] = note
    return out


def teammate_bumps(league: str, games: list[dict], inj: dict, pbook, model, per_team: int = 10) -> dict:
    """{player_id: bump} for NBA players whose team is missing high-minute players that the recent logs
    don't already reflect. (NFL: left to the market; usage redistribution there is too position-specific.)"""
    if league != "nba":
        return {}
    from . import props  # local: avoid import cycle
    bumps: dict[str, float] = {}
    for g in games:
        for tid in (g["home"], g["away"]):
            ids = team_game_ids(model, tid)
            recent = ids[:10]
            if not recent:
                continue
            ros = [p for p in pbook.by_name.values() if p["team_id"] == tid]
            pbook.prefetch([p["id"] for p in ros], full=False)
            lost = 0.0
            for p in ros:
                v = inj.get(espn.norm_name(p["name"]))
                if not v or v["status"].lower() not in OUT:
                    continue
                rows = pbook.cur.get(p["id"]) or []
                if not rows:
                    continue
                mins = sum(r.get("minutes") or 0 for r in rows[:15]) / min(len(rows), 15)
                if mins < 20:
                    continue
                games_in_recent = sum(1 for r in rows if r.get("event_id") in set(recent))
                already = 1 - games_in_recent / len(recent)   # share of recent games the log already lacks him
                lost += mins * max(0.0, 1 - already)
            if lost <= 0:
                continue
            bump = min(TEAMMATE_BUMP_CAP, lost * TEAMMATE_BUMP_PER_MIN)
            for p in props.key_players(league, pbook, tid, per_team):
                if inj.get(espn.norm_name(p["name"]), {}).get("status", "").lower() in OUT:
                    continue
                bumps[p["id"]] = bump
    return bumps


class Availability:
    """Per-slate lookup used by the prop and projection-sheet code."""

    def __init__(self, league: str, model, pbook, inj: dict, games: list[dict]):
        self.league, self.model, self.pbook, self.inj = league, model, pbook, inj
        self._ids: dict[str, list[str]] = {}
        try:
            self.bumps = teammate_bumps(league, games, inj, pbook, model)
        except Exception:                      # never lose the card over this layer
            self.bumps = {}

    def status(self, player: dict) -> dict:
        tid = player["team_id"]
        if tid not in self._ids:
            self._ids[tid] = team_game_ids(self.model, tid)
        rows = self.pbook.cur.get(player["id"])
        if rows is None:
            rows = self.pbook.current_log(player["id"])
        return player_status(rows or [], self._ids[tid], self.league)

    def uncertain(self, nname: str) -> str:
        v = self.inj.get(nname)
        return v["status"] if v and v["status"].lower() in UNCERTAIN else ""

    def project(self, player: dict, proj: dict | None) -> dict | None:
        if not proj:
            return proj
        try:
            st = self.status(player)
        except Exception:
            st = None
        return adjust_projection(self.league, proj, st, self.bumps.get(player["id"], 0.0))
