"""Walk-forward test of NFL player-prop projections (weekly nflverse stats, 2020-2025).

Compares, on test seasons 2023-2025 (trained only on earlier seasons):
  A. current  - production props.project() (recency-weighted mean, normal/NB, 20% shrink toward 50/50)
  B. current + Platt recalibration (trained on earlier seasons)
  C. ridge projection (recent form, season baseline, game script, opponent allowance, home) with
     gamma (yards) / negative-binomial (counts) distributions whose variance is fitted, not assumed.

IMPORTANT LIMITATION: no free historical prop lines exist, so "the line" is a PROXY: the player's trailing
8-game median rounded to a half point. Hit-rates vs the proxy test calibration and bias, not profit.

Run: python3 outputs/job-6/scripts/eval_props.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as st
from sklearn.linear_model import LogisticRegression, Ridge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1] / "bets"))
from betmodel import props  # noqa: E402

np.random.seed(7)
DATA, OUT = ROOT / "data", ROOT / "results"
OUT.mkdir(exist_ok=True)

# stat -> (column(s), positions, min trailing mean to be in "prop universe", count?)
STATS = {
    "pass_yds": (["passing_yards"], ["QB"], 150, False),
    "pass_att": (["attempts"], ["QB"], 20, True),
    "completions": (["completions"], ["QB"], 12, True),
    "rush_yds": (["rushing_yards"], ["RB"], 25, False),
    "rush_att": (["carries"], ["RB"], 8, True),
    "receptions": (["receptions"], ["WR", "TE", "RB"], 2, True),
    "rec_yds": (["receiving_yards"], ["WR", "TE", "RB"], 25, False),
}
# production field names for props.NFL_STATS functions
PROD_FIELD = {"passing_yards": "passingYards", "attempts": "passingAttempts", "completions": "completions",
              "rushing_yards": "rushingYards", "carries": "rushingAttempts", "receptions": "receptions",
              "receiving_yards": "receivingYards"}
PROD_STAT = {"pass_yds": "pass_yds", "pass_att": "pass_att", "completions": "completions", "rush_yds": "rush_yds",
             "rush_att": "rush_att", "receptions": "receptions", "rec_yds": "rec_yds"}


def load():
    pl = pd.concat([pd.read_csv(DATA / ("nfl_player_week_%d.csv" % y)) for y in range(2020, 2026)], ignore_index=True)
    pl = pl[pl.season_type == "REG"].copy()
    g = pd.read_csv(DATA / "nfl_games.csv")
    g = g[(g.season >= 2020) & (g.game_type == "REG")]
    rows = []
    for _, r in g.iterrows():
        if pd.isna(r.spread_line) or pd.isna(r.total_line):
            continue
        rows.append((r.season, r.week, r.home_team, r.away_team, r.total_line / 2 + r.spread_line / 2, 1, r.home_score))
        rows.append((r.season, r.week, r.away_team, r.home_team, r.total_line / 2 - r.spread_line / 2, 0, r.away_score))
    gm = pd.DataFrame(rows, columns=["season", "week", "team", "opp", "implied", "home", "pts"])
    gm = gm.sort_values(["team", "season", "week"])
    # team scoring baseline = mean of the team's previous 8 games (same idea as ratings.team_baseline)
    gm["base"] = gm.groupby("team")["pts"].transform(lambda s: s.shift(1).rolling(8, min_periods=3).mean())
    gm["env"] = (gm["implied"] / gm["base"]).clip(0.85, 1.18).fillna(1.0)
    pl = pl.merge(gm[["season", "week", "team", "implied", "home", "env"]], on=["season", "week", "team"], how="left")
    pl["env"] = pl["env"].fillna(1.0)
    pl["implied"] = pl["implied"].fillna(22.5)
    pl["home"] = pl["home"].fillna(0.5)
    pl["t"] = pl.season * 100 + pl.week
    return pl.sort_values(["player_id", "t"]).reset_index(drop=True)


def ewma_prior(vals, hl):
    """Weighted mean of PRIOR values (newest weighted most), per row; NaN if none."""
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if i == 0:
            continue
        v = vals[max(0, i - 40):i][::-1]
        w = 0.5 ** (np.arange(len(v)) / hl)
        out[i] = (v * w).sum() / w.sum()
    return out


def build(stat, pl):
    cols, poss, thresh, is_count = STATS[stat]
    d = pl[pl.position.isin(poss)].copy()
    d["y"] = d[cols].sum(axis=1)
    if stat in ("pass_yds", "pass_att", "completions"):
        d = d[d.attempts >= 8]
    feats = []
    for pid, grp in d.groupby("player_id", sort=False):
        y = grp["y"].values.astype(float)
        f = pd.DataFrame({"idx": grp.index, "ew3": ewma_prior(y, 3), "ew6": ewma_prior(y, 6),
                          "ew20": ewma_prior(y, 20), "n_prior": np.arange(len(y)).clip(max=40)})
        f["med8"] = [np.median(y[max(0, i - 8):i]) if i else np.nan for i in range(len(y))]
        f["last3"] = [y[max(0, i - 3):i].mean() if i else np.nan for i in range(len(y))]
        feats.append(f)
    f = pd.concat(feats).set_index("idx")
    d = d.join(f)
    d = d[(d.n_prior >= 4) & (d.ew6 >= thresh)].copy()
    # opponent allowance: mean of this stat allowed by the opponent to the same positions over its prior 8 games,
    # relative to the league mean over the same window (uses only earlier weeks)
    allow = d.groupby(["season", "week", "opponent_team"])["y"].sum().reset_index()
    allow = allow.sort_values(["opponent_team", "season", "week"])
    allow["roll"] = allow.groupby("opponent_team")["y"].transform(lambda s: s.shift(1).rolling(8, min_periods=3).mean())
    lg = allow.groupby(["season", "week"])["y"].mean().rename("lg").reset_index()
    lg["lg_roll"] = lg["lg"].shift(1).rolling(16, min_periods=4).mean()
    allow = allow.merge(lg[["season", "week", "lg_roll"]], on=["season", "week"])
    allow["opp_rel"] = (allow["roll"] / allow["lg_roll"]).clip(0.6, 1.5)
    d = d.merge(allow[["season", "week", "opponent_team", "opp_rel"]], on=["season", "week", "opponent_team"], how="left")
    d["opp_rel"] = d["opp_rel"].fillna(1.0)
    d["line"] = np.floor(d["med8"]) + 0.5
    return d.reset_index(drop=True), is_count


def rows_for_prod(pl_player, i):
    """Production-style game log (newest first) for one player-week index into that player's frame."""
    return None


def current_probs(d, pl, stat):
    """Run production props.project on each row with adapter rows; returns mean, sd, p_over arrays."""
    cols = STATS[stat][0]
    pos = STATS[stat][1]
    p = pl[pl.position.isin(pos)]
    by_player = {pid: g for pid, g in p.groupby("player_id")}
    means, sds, pov = [], [], []
    for r in d.itertuples():
        g = by_player[r.player_id]
        prior = g[(g.t < r.t)].tail(40)
        logs = []
        for q in prior.iloc[::-1].itertuples():
            row = {PROD_FIELD[c]: getattr(q, c) for c in cols}
            row["_prev"] = q.season < r.season
            logs.append(row)
        pr = props.project("nfl", logs, PROD_STAT[stat], float(r.env))
        if pr is None:
            means.append(np.nan); sds.append(np.nan); pov.append(np.nan)
            continue
        o, u, pu = props.model_probs(pr, r.line)
        means.append(pr["mean"]); sds.append(pr["sd"]); pov.append(o / max(o + u, 1e-9))
    return np.array(means), np.array(sds), np.array(pov)


FEATS = ["ew3", "ew6", "ew20", "last3", "n_prior", "implied", "home", "opp_rel"]


def fit_var(mu, resid2, nb=10):
    """var = a * mu^b from binned squared residuals."""
    q = pd.qcut(mu, nb, duplicates="drop")
    g = pd.DataFrame({"mu": mu, "r2": resid2, "q": q}).groupby("q", observed=True).mean()
    b, _ = np.polyfit(np.log(g.mu.values), np.log(g.r2.values), 1)
    b = float(np.clip(b, 0.8, 2.0))
    # re-fit the intercept after clipping the exponent (a clipped slope with the old intercept was a bug)
    la = float(np.mean(np.log(g.r2.values)) - b * np.mean(np.log(g.mu.values)))
    return math.exp(la), b


def p_over(mu, var, line, is_count):
    mu = np.maximum(mu, 0.3)
    if is_count:
        var = np.maximum(var, mu * 1.02)
        r = mu * mu / (var - mu)
        p = r / (r + mu)
        k = np.ceil(line).astype(int)  # P(X >= k) for x.5 lines
        return 1 - st.nbinom.cdf(k - 1, r, p)
    shape = mu * mu / var
    scale = var / mu
    return st.gamma.sf(line, shape, scale=scale)


def ll(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def main():
    pl = load()
    results = {}
    for stat in STATS:
        d, is_count = build(stat, pl)
        d["mean_cur"], d["sd_cur"], d["p_cur"] = current_probs(d, pl, stat)
        d = d.dropna(subset=["mean_cur"]).copy()
        d["over"] = (d["y"] > d["line"]).astype(float)
        out = {"A_current": {"p": [], "y": []}, "B_current_platt": {"p": [], "y": []}, "C_ridge_dist": {"p": [], "y": []},
               "bias": {}}
        tmp = []
        for ty in (2023, 2024, 2025):
            tr, te = d[(d.season < ty) & (d.season >= 2021)], d[d.season == ty].copy()
            X = lambda x: x[FEATS].fillna(x[FEATS].mean()).values  # noqa: E731
            rg = Ridge(alpha=10.0).fit(X(tr), tr["y"])
            mu_tr, mu_te = np.maximum(rg.predict(X(tr)), 0.3), np.maximum(rg.predict(X(te)), 0.3)
            a, b = fit_var(mu_tr, (tr["y"].values - mu_tr) ** 2)
            pc = p_over(mu_te, a * mu_te ** b, te["line"].values, is_count)
            lp = LogisticRegression(C=10).fit(np.log(tr[["p_cur"]].clip(0.02, 0.98) / (1 - tr[["p_cur"]].clip(0.02, 0.98))), tr["over"])
            pp = lp.predict_proba(np.log(te[["p_cur"]].clip(0.02, 0.98) / (1 - te[["p_cur"]].clip(0.02, 0.98))))[:, 1]
            te["mu_c"], te["p_c"], te["p_platt"] = mu_te, pc, pp
            tmp.append(te)
        t = pd.concat(tmp)
        y = t["over"].values
        res = {"n": int(len(t)), "base_over_rate": float(y.mean()),
               "A_current": {"logloss": ll(t.p_cur.values, y), "brier": float(np.mean((t.p_cur - y) ** 2)),
                             "mean_p_over": float(t.p_cur.mean())},
               "B_current_platt": {"logloss": ll(t.p_platt.values, y), "brier": float(np.mean((t.p_platt - y) ** 2)),
                                   "mean_p_over": float(t.p_platt.mean())},
               "C_ridge_dist": {"logloss": ll(t.p_c.values, y), "brier": float(np.mean((t.p_c - y) ** 2)),
                                "mean_p_over": float(t.p_c.mean())},
               "naive_50": {"logloss": ll(np.full(len(y), 0.5), y)},
               "mean_error_current": float((t.y - t.mean_cur).mean()),
               "mean_error_ridge": float((t.y - t.mu_c).mean()),
               "mae_current": float((t.y - t.mean_cur).abs().mean()), "mae_ridge": float((t.y - t.mu_c).abs().mean()),
               "mae_median_proxy": float((t.y - t.med8).abs().mean()),
               "pct_actual_below_current_mean": float((t.y < t.mean_cur).mean())}
        # "strong under" claims: where each model says P(under) >= 0.60 how often does under actually hit?
        for k, col in (("A_current", "p_cur"), ("B_current_platt", "p_platt"), ("C_ridge_dist", "p_c")):
            for side, mask in (("under", t[col] <= 0.40), ("over", t[col] >= 0.60)):
                m = mask.values
                hit = (1 - y[m]) if side == "under" else y[m]
                claimed = (1 - t[col].values[m]) if side == "under" else t[col].values[m]
                res[k]["%s_claims60+" % side] = {"n": int(m.sum()), "claimed": float(claimed.mean()) if m.sum() else None,
                                                  "hit_rate": float(hit.mean()) if m.sum() else None}
        res["under_share_of_60plus_current"] = float((t.p_cur <= 0.40).sum() / max(1, ((t.p_cur <= 0.40) | (t.p_cur >= 0.60)).sum()))
        # by season bias
        res["bias_by_pos"] = {pos: float((g.y - g.mean_cur).mean()) for pos, g in t.groupby("position")}
        # reliability bins for A and C
        for k, col in (("A_current", "p_cur"), ("C_ridge_dist", "p_c")):
            q = pd.qcut(t[col], 8, duplicates="drop")
            gb = t.groupby(q, observed=True).agg(p=(col, "mean"), o=("over", "mean"), n=("over", "size"))
            res[k]["bins"] = [{"p_pred": float(r.p), "p_obs": float(r.o), "n": int(r.n)} for r in gb.itertuples()]
        lg_ = np.log(t[["p_cur"]].clip(0.02, 0.98) / (1 - t[["p_cur"]].clip(0.02, 0.98)))
        pf = LogisticRegression(C=10).fit(lg_, t["over"])
        res["platt_all_oos"] = {"a": float(pf.intercept_[0]), "b": float(pf.coef_[0][0])}
        results[stat] = res
        print(stat, res["n"], "ll cur %.4f platt %.4f ridge %.4f naive %.4f | MAE cur %.2f ridge %.2f med %.2f | err cur %+.2f ridge %+.2f" % (
            res["A_current"]["logloss"], res["B_current_platt"]["logloss"], res["C_ridge_dist"]["logloss"],
            res["naive_50"]["logloss"], res["mae_current"], res["mae_ridge"], res["mae_median_proxy"],
            res["mean_error_current"], res["mean_error_ridge"]), flush=True)
    (OUT / "props_metrics.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
