"""Player-prop projections and pricing.

Projection = recency-weighted average of the player's game log (this season +
last season at reduced weight), scaled by the game environment (DraftKings
implied team total vs the team's normal scoring), with a distribution fitted to
the player's own variance (negative binomial for low counts, normal otherwise).
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor

from . import espn
from .common import prob_over_under, weighted_mean_sd

# canonical stat -> (function of a game-log row, environment exponent)
NBA_STATS = {
    "points": (lambda r: r.get("points"), 1.0),
    "rebounds": (lambda r: r.get("totalRebounds"), 0.3),
    "assists": (lambda r: r.get("assists"), 0.8),
    "threes": (lambda r: r.get("threePointFieldGoalsMade"), 1.0),
    "blocks": (lambda r: r.get("blocks"), 0.0),
    "steals": (lambda r: r.get("steals"), 0.0),
    "turnovers": (lambda r: r.get("turnovers"), 0.3),
    "pra": (lambda r: _sum(r, "points", "totalRebounds", "assists"), 0.8),
    "pr": (lambda r: _sum(r, "points", "totalRebounds"), 0.8),
    "pa": (lambda r: _sum(r, "points", "assists"), 0.9),
    "ra": (lambda r: _sum(r, "totalRebounds", "assists"), 0.5),
    "blk_stl": (lambda r: _sum(r, "blocks", "steals"), 0.0),
}
NFL_STATS = {
    "pass_yds": (lambda r: r.get("passingYards"), 0.6),
    "pass_tds": (lambda r: r.get("passingTouchdowns"), 1.0),
    "pass_att": (lambda r: r.get("passingAttempts"), 0.0),
    "completions": (lambda r: r.get("completions"), 0.3),
    "interceptions": (lambda r: r.get("interceptions"), 0.0),
    "rush_yds": (lambda r: r.get("rushingYards"), 0.5),
    "rush_att": (lambda r: r.get("rushingAttempts"), 0.3),
    "receptions": (lambda r: r.get("receptions"), 0.4),
    "rec_yds": (lambda r: r.get("receivingYards"), 0.6),
    "rush_rec_yds": (lambda r: _sum(r, "rushingYards", "receivingYards"), 0.6),
    "anytime_td": (lambda r: _sum(r, "rushingTouchdowns", "receivingTouchdowns"), 1.0),
}
STATS = {"nba": NBA_STATS, "nfl": NFL_STATS}
STAT_ALIASES = {  # how people (and Underdog) name things
    "pts": "points", "reb": "rebounds", "rebs": "rebounds", "ast": "assists", "asts": "assists",
    "3pm": "threes", "3s": "threes", "3-pointers made": "threes", "three pointers made": "threes",
    "pts+rebs+asts": "pra", "points+rebounds+assists": "pra", "pts+rebs": "pr", "pts+asts": "pa",
    "rebs+asts": "ra", "blks+stls": "blk_stl", "blocks+steals": "blk_stl",
    "passing yards": "pass_yds", "pass yards": "pass_yds", "passing tds": "pass_tds",
    "rushing yards": "rush_yds", "rush yards": "rush_yds", "receiving yards": "rec_yds",
    "rec yards": "rec_yds", "rush + rec yards": "rush_rec_yds", "rush+rec yards": "rush_rec_yds",
    "rushing attempts": "rush_att", "pass attempts": "pass_att", "pass completions": "completions",
    "anytime td": "anytime_td", "rush+rec tds": "anytime_td",
}

HALF_LIFE_GAMES = {"nba": 10, "nfl": 6}
PREV_SEASON_WEIGHT = 0.35
MINUTES_HALF_LIFE = 4  # NBA: expected minutes follow the last few games closely
PRIOR_GAMES = 5  # strength of the variance prior
CV_PRIOR = {"nba": 0.32, "nfl": 0.55}  # typical coefficient of variation for continuous stats
DISCRETE_BELOW = 12.0  # mean below this -> negative binomial
MODEL_SHRINK = 0.8  # pull raw model probabilities 20% toward 50% (models are overconfident)


def _sum(r, *keys):
    vals = [r.get(k) for k in keys]
    return None if any(v is None for v in vals) else sum(vals)


def canon_stat(league: str, s: str) -> str | None:
    s = s.strip().lower()
    s = STAT_ALIASES.get(s, s).replace(" ", "_")
    return s if s in STATS[league] else None


class PlayerBook:
    """Caches rosters + game logs for the teams on a slate and maps names -> ids."""

    def __init__(self, league: str, season: int):
        self.league, self.season = league, season
        self.by_name: dict[str, dict] = {}
        self.logs: dict[str, list[dict]] = {}
        self.cur: dict[str, list[dict]] = {}

    def load_teams(self, team_ids):
        with ThreadPoolExecutor(8) as ex:
            for ros in ex.map(lambda t: _safe(espn.roster, self.league, t), team_ids):
                for p in ros or []:
                    self.by_name[espn.norm_name(p["name"])] = p

    def find(self, name: str) -> dict | None:
        n = espn.norm_name(name)
        if n in self.by_name:
            return self.by_name[n]
        # fallback: same last name + first initial (handles 'Nic' vs 'Nicolas')
        parts = n.split()
        if len(parts) >= 2:
            cands = [p for k, p in self.by_name.items()
                     if k.split()[-1] == parts[-1] and k[0] == parts[0][0]]
            if len(cands) == 1:
                return cands[0]
        return None

    def _clean(self, rows):
        if self.league == "nba":
            rows = [r for r in rows if (r.get("minutes") or 0) > 0]
        return rows

    def current_log(self, athlete_id: str) -> list[dict]:
        """This season only (cheap; used to rank who plays)."""
        if athlete_id not in self.cur:
            self.cur[athlete_id] = self._clean(espn.gamelog(self.league, athlete_id))
        return self.cur[athlete_id]

    def log(self, athlete_id: str) -> list[dict]:
        """This season + last season (flagged _prev), newest first."""
        if athlete_id not in self.logs:
            prev = [dict(r, _prev=True) for r in espn.gamelog(self.league, athlete_id, self.season - 1)]
            self.logs[athlete_id] = self.current_log(athlete_id) + self._clean(prev)
        return self.logs[athlete_id]

    def prefetch(self, athlete_ids, full: bool = True):
        fn = self.log if full else self.current_log
        store = self.logs if full else self.cur
        todo = [a for a in set(athlete_ids) if a not in store]
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda a: _safe(fn, a), todo))


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:  # one bad player/team must not kill the slate
        return None


def project(league: str, rows: list[dict], stat: str, env_factor: float = 1.0) -> dict | None:
    """Mean/sd/n for a stat from game-log rows (newest first). None if too little data."""
    fn, exponent = STATS[league][stat]
    vals, wts = [], []
    hl = HALF_LIFE_GAMES[league]
    for i, r in enumerate(rows[:60]):
        v = fn(r)
        if v is None:
            continue
        w = 0.5 ** (i / hl) * (PREV_SEASON_WEIGHT if r.get("_prev") else 1.0)
        vals.append(v)
        wts.append(w)
    mean, sd, n_eff = weighted_mean_sd(vals, wts)
    if n_eff < 2.5 or len(vals) < 3:
        return None
    if league == "nba" and mean > 0:
        # role changes show up in minutes first: per-minute production x expected minutes now
        mins = [r.get("minutes") or 0.0 for r in rows[:60] if fn(r) is not None]
        tot_min = sum(m * w for m, w in zip(mins, wts))
        cur_min = [r.get("minutes") or 0.0 for r in rows[:10] if not r.get("_prev")]
        if tot_min > 0:
            rate = sum(v * w for v, w in zip(vals, wts)) / tot_min
            if len(cur_min) >= 3:
                mw = [0.5 ** (i / MINUTES_HALF_LIFE) for i in range(len(cur_min))]
                exp_min = sum(m * w for m, w in zip(cur_min, mw)) / sum(mw)
            else:
                exp_min = tot_min / sum(wts)
            new_mean = rate * exp_min
            sd *= (new_mean / mean) ** 0.5  # spread grows slower than the mean
            mean = new_mean
    factor = env_factor ** exponent
    mean *= factor
    sd *= factor
    discrete = mean < DISCRETE_BELOW
    prior_var = mean * 1.25 if discrete else (CV_PRIOR[league] * mean) ** 2
    var = (n_eff * sd * sd + PRIOR_GAMES * prior_var) / (n_eff + PRIOR_GAMES)
    if discrete:
        var = max(var, mean * 1.02)
    cur_games = sum(1 for r in rows if not r.get("_prev"))
    return {"mean": mean, "sd": math.sqrt(var), "n_eff": n_eff, "discrete": discrete,
            "games_this_season": cur_games, "last5": [fn(r) for r in rows[:5]]}


def model_probs(proj: dict, line: float) -> tuple[float, float, float]:
    """Shrunk (P over, P under, P push)."""
    o, u, push = prob_over_under(line, proj["mean"], proj["sd"], proj["discrete"])
    played = o + u
    if played <= 0:
        return 0.0, 0.0, 1.0
    o_n = 0.5 + MODEL_SHRINK * (o / played - 0.5)
    return o_n * played, (1 - o_n) * played, push


def fair_line(proj: dict) -> float:
    """Half-point line closest to 50/50 under the model."""
    best, best_gap = None, 9e9
    lo = max(0.5, math.floor(proj["mean"] - 3 * proj["sd"]) + 0.5)
    x = lo
    while x <= proj["mean"] + 3 * proj["sd"] + 1:
        o, _, _ = prob_over_under(x, proj["mean"], proj["sd"], proj["discrete"])
        if abs(o - 0.5) < best_gap:
            best, best_gap = x, abs(o - 0.5)
        x += 1.0
    return best if best is not None else math.floor(proj["mean"]) + 0.5


def threshold_lines(proj: dict, target: float) -> tuple[float | None, float | None]:
    """(highest line where OVER has model prob >= target, lowest line where UNDER does)."""
    over_at = under_at = None
    x = 0.5
    top = proj["mean"] + 5 * proj["sd"] + 2
    while x <= top:
        o, u, _ = model_probs(proj, x)
        if o >= target:
            over_at = x
        if u >= target and under_at is None:
            under_at = x
        x += 1.0
    return over_at, under_at


def key_players(league: str, book: PlayerBook, team_id: str, per_team: int) -> list[dict]:
    """Players worth projecting for a team: NBA by minutes, NFL skill positions by usage."""
    ros = [p for p in book.by_name.values() if p["team_id"] == team_id]
    if league == "nfl":
        ros = [p for p in ros if p["pos"] in ("QB", "RB", "WR", "TE")]
    book.prefetch([p["id"] for p in ros], full=False)
    scored = []
    for p in ros:
        rows = (book.cur.get(p["id"]) or [])[:5]
        if not rows:
            continue
        if league == "nba":
            usage = sum(r.get("minutes") or 0 for r in rows) / len(rows)
        else:
            usage = sum((r.get("passingAttempts") or 0) * 0.5 + (r.get("rushingAttempts") or 0)
                        + (r.get("receivingTargets") or 0) * 1.5 for r in rows) / len(rows)
        scored.append((usage, p))
    scored.sort(key=lambda x: -x[0])
    if league == "nfl":  # keep only the starting QB
        out, qb = [], False
        for _, p in scored:
            if p["pos"] == "QB":
                if qb:
                    continue
                qb = True
            out.append(p)
        return out[:per_team]
    return [p for _, p in scored[:per_team]]


DEFAULT_SHEET_STATS = {
    "nba": ["points", "rebounds", "assists", "threes", "pra"],
    "nfl": {"QB": ["pass_yds", "pass_tds", "rush_yds"], "RB": ["rush_yds", "rec_yds", "receptions", "anytime_td"],
            "WR": ["rec_yds", "receptions", "anytime_td"], "TE": ["rec_yds", "receptions", "anytime_td"]},
}


def sheet_stats(league: str, pos: str) -> list[str]:
    d = DEFAULT_SHEET_STATS[league]
    return d if isinstance(d, list) else d.get(pos, [])
