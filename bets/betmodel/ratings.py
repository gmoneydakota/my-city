"""Team strength model: opponent-adjusted offence/defence ratings.

    points(team vs opp) = mu + home_edge/2 + off[team] - def[opp]

Fit by weighted ridge regression (coordinate descent) on this season + last season.
Recent games weigh more; last season is down-weighted so early-season ratings
aren't driven by 5 games. Gives expected score for both sides, so it prices
moneylines, spreads and totals from one model.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from . import espn
from .common import norm_cdf

CONFIG = {
    # half_life: days for a game's weight to halve; prev_weight: extra multiplier for last season
    # ridge: shrinkage toward average (in "games" of evidence); sigma_*: fallback residual sd
    "nba": {"half_life": 45, "prev_weight": 0.5, "ridge": 6.0, "sigma_margin": 12.5, "sigma_total": 18.5,
            "b2b_penalty": 1.5},
    "nfl": {"half_life": 120, "prev_weight": 0.45, "ridge": 3.0, "sigma_margin": 13.5, "sigma_total": 13.5,
            "b2b_penalty": 0.0},
}


class TeamModel:
    def __init__(self, league: str):
        self.league = league
        self.cfg = CONFIG[league]
        self.off: dict[str, float] = {}
        self.deff: dict[str, float] = {}
        self.mu = 0.0
        self.hca = 0.0
        self.sigma_margin = self.cfg["sigma_margin"]
        self.sigma_total = self.cfg["sigma_total"]
        self.n_games = 0
        self.schedule: list[dict] = []

    # ------------------------------------------------------------------ fitting
    def fit(self, games: list[dict], asof: datetime, current_season_start: datetime | None = None):
        played = [g for g in games if g["final"] and g["home_score"] is not None and g["date"] < asof]
        if not played:
            raise ValueError("no completed games to fit")
        hl = self.cfg["half_life"]
        rows = []
        for g in played:
            age = (asof - g["date"]).total_seconds() / 86400
            w = 0.5 ** (age / hl)
            if current_season_start and g["date"] < current_season_start:
                w *= self.cfg["prev_weight"]
            rows.append((g["home"], g["away"], g["home_score"], g["away_score"], 0.0 if g["neutral"] else 1.0, w))
        teams = {r[0] for r in rows} | {r[1] for r in rows}
        off = {t: 0.0 for t in teams}
        deff = {t: 0.0 for t in teams}
        sw = sum(r[5] for r in rows)
        mu = sum(r[5] * (r[2] + r[3]) / 2 for r in rows) / sw
        hca = 0.0
        lam = self.cfg["ridge"]
        for _ in range(60):
            # home edge (in points of margin) from home games only
            num = den = 0.0
            for h, a, hs, as_, home, w in rows:
                if home:
                    num += w * ((hs - (mu + off[h] - deff[a])) - (as_ - (mu + off[a] - deff[h])))
                    den += w
            hca = num / den if den else 0.0
            mu = sum(w * ((hs - hm * hca / 2 - off[h] + deff[a]) + (as_ + hm * hca / 2 - off[a] + deff[h])) / 2
                     for h, a, hs, as_, hm, w in rows) / sw
            acc_o = {t: [0.0, lam] for t in teams}
            for h, a, hs, as_, hm, w in rows:
                acc_o[h][0] += w * (hs - mu - hm * hca / 2 + deff[a]); acc_o[h][1] += w
                acc_o[a][0] += w * (as_ - mu + hm * hca / 2 + deff[h]); acc_o[a][1] += w
            off = {t: s / n for t, (s, n) in acc_o.items()}
            acc_d = {t: [0.0, lam] for t in teams}
            for h, a, hs, as_, hm, w in rows:
                acc_d[a][0] += w * (mu + hm * hca / 2 + off[h] - hs); acc_d[a][1] += w
                acc_d[h][0] += w * (mu - hm * hca / 2 + off[a] - as_); acc_d[h][1] += w
            deff = {t: s / n for t, (s, n) in acc_d.items()}
        self.off, self.deff, self.mu, self.hca = off, deff, mu, hca
        # residual spread of margins/totals (weighted), floored at sensible values
        em = et = 0.0
        for h, a, hs, as_, hm, w in rows:
            ph, pa = self._pts(h, a, hm)
            em += w * ((hs - as_) - (ph - pa)) ** 2
            et += w * ((hs + as_) - (ph + pa)) ** 2
        self.sigma_margin = max(math.sqrt(em / sw), self.cfg["sigma_margin"] * 0.85)
        self.sigma_total = max(math.sqrt(et / sw), self.cfg["sigma_total"] * 0.85)
        self.n_games = len(rows)
        return self

    def _pts(self, home: str, away: str, home_flag: float = 1.0) -> tuple[float, float]:
        ph = self.mu + home_flag * self.hca / 2 + self.off.get(home, 0) - self.deff.get(away, 0)
        pa = self.mu - home_flag * self.hca / 2 + self.off.get(away, 0) - self.deff.get(home, 0)
        return ph, pa

    # ------------------------------------------------------------------ prediction
    def rest_adjust(self, team: str, when: datetime) -> float:
        """Points lost to a back-to-back (NBA) based on the team's schedule."""
        pen = self.cfg["b2b_penalty"]
        if not pen:
            return 0.0
        for g in self.schedule:
            if team in (g["home"], g["away"]) and timedelta(hours=8) < when - g["date"] < timedelta(hours=34):
                return -pen
        return 0.0

    def predict(self, home: str, away: str, when: datetime, neutral: bool = False,
                adj_home: float = 0.0, adj_away: float = 0.0) -> dict:
        """adj_*: extra margin points for that team (e.g. injuries, negative = weaker)."""
        ph, pa = self._pts(home, away, 0.0 if neutral else 1.0)
        rh = self.rest_adjust(home, when) + adj_home
        ra = self.rest_adjust(away, when) + adj_away
        ph += rh / 2; pa -= rh / 2
        pa += ra / 2; ph -= ra / 2
        margin = ph - pa
        return {
            "home_pts": ph, "away_pts": pa, "margin": margin, "total": ph + pa,
            "p_home": norm_cdf(margin / self.sigma_margin),
            "home_b2b": self.rest_adjust(home, when) < 0, "away_b2b": self.rest_adjust(away, when) < 0,
        }

    def p_home_cover(self, margin: float, home_line: float) -> float:
        """P(home margin + home_line > 0), ignoring pushes."""
        return norm_cdf((margin + home_line) / self.sigma_margin)

    def p_over(self, total: float, line: float) -> float:
        return 1 - norm_cdf((line - total) / self.sigma_total)

    def team_baseline(self, team: str) -> float:
        """Points vs an average defence at a neutral site."""
        return self.mu + self.off.get(team, 0.0)


def build(league: str, asof: datetime | None = None) -> TeamModel:
    asof = asof or datetime.now(timezone.utc)
    season = espn.current_season(league)
    cur = espn.league_games(league, season)
    prev = espn.league_games(league, season - 1)
    start = min((g["date"] for g in cur), default=None)
    m = TeamModel(league)
    m.schedule = cur
    m.fit(prev + cur, asof, start)
    return m


def backtest(league: str, step_days: int = 14) -> dict:
    """Walk-forward test on last completed season: refit every ``step_days`` and
    score next-window games. Reports win accuracy, Brier score and margin MAE."""
    season = espn.current_season(league) - 1
    prev = espn.league_games(league, season - 1)
    games = [g for g in espn.league_games(league, season) if g["final"] and g["home_score"] is not None]
    if len(games) < 50:
        return {"error": "not enough games"}
    start = games[0]["date"]
    t = start + timedelta(days=21)
    end = games[-1]["date"]
    n = correct = 0
    brier = mae = 0.0
    while t <= end:
        m = TeamModel(league)
        m.schedule = games
        m.fit(prev + games, t, start)
        for g in games:
            if t <= g["date"] < t + timedelta(days=step_days):
                p = m.predict(g["home"], g["away"], g["date"], g["neutral"])
                actual = g["home_score"] - g["away_score"]
                if actual == 0:
                    continue
                won = 1.0 if actual > 0 else 0.0
                n += 1
                correct += (p["p_home"] > 0.5) == bool(won)
                brier += (p["p_home"] - won) ** 2
                mae += abs(p["margin"] - actual)
        t += timedelta(days=step_days)
    return {"season": season, "games": n, "accuracy": correct / n, "brier": brier / n, "margin_mae": mae / n,
            "note": "Brier 0.25 = coin flip, lower is better; closing betting lines usually score somewhat "
                    "better than any public-data model, which is why picks blend in the market"}
