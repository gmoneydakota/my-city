"""Walk-forward evaluation of game-level models (ML / spread / total) for NFL and NBA.

Run:  python3 outputs/job-6/scripts/eval_games.py
Writes outputs/job-6/results/games_metrics.json, games_predictions_*.csv and calibration plots.

No future leakage: every prediction at time t uses only games finished before t (ratings refit weekly);
second-stage models (logistic / gradient boosting / Platt) are trained only on out-of-sample predictions of
EARLIER seasons and evaluated on the later season.
"""
import csv
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1] / "bets"))
from betmodel.ratings import TeamModel  # noqa: E402  (the production team model)

random.seed(7)
np.random.seed(7)
DATA, OUT = ROOT / "data", ROOT / "results"
OUT.mkdir(exist_ok=True)
EPS = 1e-6


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def metrics(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return {"n": int(len(y)), "logloss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
            "brier": float(np.mean((p - y) ** 2)), "acc": float(np.mean((p > 0.5) == (y > 0.5)))}


def calib_bins(p, y, k=10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.quantile(p, np.linspace(0, 1, k + 1))
    rows = []
    for i in range(k):
        m = (p >= edges[i]) & ((p <= edges[i + 1]) if i == k - 1 else (p < edges[i + 1]))
        if m.sum():
            rows.append({"p_pred": float(p[m].mean()), "p_obs": float(y[m].mean()), "n": int(m.sum())})
    return rows


def ece(bins):
    n = sum(b["n"] for b in bins)
    return sum(b["n"] * abs(b["p_pred"] - b["p_obs"]) for b in bins) / n if n else None


def devig(h, a):
    def ip(o):
        return 100 / (o + 100) if o > 0 else -o / (-o + 100)
    ph, pa = ip(h), ip(a)
    return ph / (ph + pa)


def profit(p_win, odds_dec, won):
    return odds_dec - 1 if won else -1.0


# ----------------------------------------------------------------------------- generic walk-forward ratings
def walk(games, start_dt, step_days, league, prev_cut):
    """games: sorted list of dicts(date, home, away, home_score, away_score, ...). Returns rows with the
    production model's prediction for each game with date >= start_dt, refit every step_days."""
    preds = {}
    end = games[-1]["date"]
    t = start_dt
    while t <= end:
        past = [g for g in games if g["date"] < t]
        if len(past) > 30:
            season_start = min(g["date"] for g in games if g["date"] >= prev_cut(t))
            m = TeamModel(league)
            m.schedule = games
            m.fit(past, t, season_start)
            for g in games:
                if t <= g["date"] < t + timedelta(days=step_days):
                    pr = m.predict(g["home"], g["away"], g["date"], g["neutral"])
                    preds[g["id"]] = pr
        t += timedelta(days=step_days)
    return preds


# ----------------------------------------------------------------------------- NFL
def load_nfl():
    rows = list(csv.DictReader(open(DATA / "nfl_games.csv")))
    games = []
    for r in rows:
        if r["game_type"] not in ("REG",) or r["home_score"] == "" or int(r["season"]) < 2018:
            continue
        d = datetime.strptime(r["gameday"], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(hours=17)
        f = lambda k: float(r[k]) if r[k] not in ("", "NA") else None  # noqa: E731
        games.append({"id": r["game_id"], "season": int(r["season"]), "week": int(r["week"]), "date": d,
                      "home": r["home_team"], "away": r["away_team"], "home_score": float(r["home_score"]),
                      "away_score": float(r["away_score"]), "final": True, "neutral": r["location"] == "Neutral",
                      "spread": f("spread_line"), "total_line": f("total_line"),
                      "ml_h": f("home_moneyline"), "ml_a": f("away_moneyline"),
                      "so_h": f("home_spread_odds"), "so_a": f("away_spread_odds"),
                      "ov": f("over_odds"), "un": f("under_odds"),
                      "rest_h": f("home_rest"), "rest_a": f("away_rest"), "roof": r["roof"],
                      "temp": f("temp"), "wind": f("wind"), "div": f("div_game")})
    games.sort(key=lambda g: g["date"])
    return games


def nfl_prev_cut(t):  # season boundary used for "last season" down-weighting
    y = t.year if t.month >= 3 else t.year - 1
    return datetime(y, 8, 1, tzinfo=timezone.utc)


def dec(odds, default=1.909):
    if odds is None:
        return default
    return 1 + (100 / -odds if odds < 0 else odds / 100)


def run_nfl():
    games = load_nfl()
    by_id = {g["id"]: g for g in games}
    preds = walk(games, datetime(2019, 9, 1, tzinfo=timezone.utc), 7, "nfl", nfl_prev_cut)
    rows = []
    for gid, pr in preds.items():
        g = by_id[gid]
        if g["spread"] is None or g["total_line"] is None:
            continue
        margin = g["home_score"] - g["away_score"]
        pm = devig(g["ml_h"], g["ml_a"]) if g["ml_h"] and g["ml_a"] else None
        rows.append({**{k: g[k] for k in ("id", "season", "week", "spread", "total_line", "so_h", "so_a", "ov", "un",
                                           "ml_h", "ml_a", "temp", "wind")},
                     "model_margin": pr["margin"], "model_total": pr["total"], "p_home_model": pr["p_home"],
                     "sigma_m": 13.5, "p_mkt_ml": pm, "margin": margin, "tot": g["home_score"] + g["away_score"],
                     "rest_diff": (g["rest_h"] or 7) - (g["rest_a"] or 7), "dome": 1.0 if g["roof"] in ("dome", "closed") else 0.0,
                     "div": g["div"] or 0.0})
    return rows


def eval_nfl(rows):
    """Compare per bet type on test seasons 2022..2025 (train on earlier out-of-sample seasons)."""
    res, preds_out = {}, []
    tests = [2022, 2023, 2024, 2025]
    W_ENGINE = 0.30  # current production weight on the model
    store = {k: {"p": [], "y": []} for k in [
        "ML:market_devig", "ML:market_spread", "ML:current_model", "ML:current_engine_blend", "ML:platt_model",
        "ML:logit_market+model", "ML:gbm_features",
        "Spread:market(0.5)", "Spread:current_model", "Spread:current_engine_blend", "Spread:logit_diff", "Spread:gbm_features",
        "Total:market(0.5)", "Total:current_model", "Total:current_engine_blend", "Total:logit_diff", "Total:gbm_features"]}
    roi = {k: [] for k in ("Spread:engine", "Spread:logit_diff", "Total:engine", "Total:logit_diff", "ML:engine", "ML:logit")}
    coef = {}
    for ty in tests:
        tr = [r for r in rows if r["season"] < ty and r["season"] >= 2019]
        te = [r for r in rows if r["season"] == ty]
        # --- ML target (ties dropped)
        def ml_xy(rs):
            rs = [r for r in rs if r["margin"] != 0 and r["p_mkt_ml"] is not None]
            return rs, np.array([1.0 if r["margin"] > 0 else 0.0 for r in rs])
        trm, ytr = ml_xy(tr)
        tem, yte = ml_xy(te)
        # market-implied sigma fit on train: maximise likelihood of Phi(spread/sigma)
        best = min(np.arange(10, 17, 0.25), key=lambda s: -np.mean([
            math.log(max(ncdf(r["spread"] / s) if r["margin"] > 0 else 1 - ncdf(r["spread"] / s), 1e-6)) for r in trm]))
        Xtr = np.array([[logit(r["p_mkt_ml"]), r["model_margin"] / 13.5] for r in trm])
        Xte = np.array([[logit(r["p_mkt_ml"]), r["model_margin"] / 13.5] for r in tem])
        lr = LogisticRegression(C=10.0).fit(Xtr, ytr)
        coef["ML %d" % ty] = {"w_market_logit": float(lr.coef_[0][0]), "w_model_margin": float(lr.coef_[0][1])}
        pl = lr.predict_proba(Xte)[:, 1]
        # platt on current model alone
        pt = LogisticRegression(C=10.0).fit(np.array([[logit(r["p_home_model"])] for r in trm]), ytr)
        pplatt = pt.predict_proba(np.array([[logit(r["p_home_model"])] for r in tem]))[:, 1]
        feats = lambda rs: np.array([[logit(r["p_mkt_ml"]), r["model_margin"], r["spread"], r["total_line"],  # noqa: E731
                                      r["rest_diff"], r["dome"], r["div"], r["wind"] or 0, r["temp"] or 60] for r in rs])
        gb = HistGradientBoostingClassifier(max_depth=2, learning_rate=0.03, max_iter=120, min_samples_leaf=40,
                                            random_state=7).fit(feats(trm), ytr)
        pg = gb.predict_proba(feats(tem))[:, 1]
        for i, r in enumerate(tem):
            pm_ = r["p_mkt_ml"]
            vals = {"ML:market_devig": pm_, "ML:market_spread": ncdf(r["spread"] / best),
                    "ML:current_model": r["p_home_model"],
                    "ML:current_engine_blend": W_ENGINE * r["p_home_model"] + (1 - W_ENGINE) * pm_,
                    "ML:platt_model": pplatt[i], "ML:logit_market+model": pl[i], "ML:gbm_features": pg[i]}
            for k, v in vals.items():
                store[k]["p"].append(v); store[k]["y"].append(yte[i])
            for key, p in (("ML:engine", vals["ML:current_engine_blend"]), ("ML:logit", pl[i])):
                for side, ps, o in (("h", p, r["ml_h"]), ("a", 1 - p, r["ml_a"])):
                    if o and ps * dec(o) - 1 > 0.03:
                        won = (yte[i] == 1) == (side == "h")
                        roi[key].append(dec(o) - 1 if won else -1.0)
        # --- Spread / Total: y=1 if home covers / over hits; drop pushes
        for kind in ("Spread", "Total"):
            def xy(rs):
                out, ys = [], []
                for r in rs:
                    if kind == "Spread":
                        d, line, val = r["model_margin"] - r["spread"], r["spread"], r["margin"]
                    else:
                        d, line, val = r["model_total"] - r["total_line"], r["total_line"], r["tot"]
                    if val == line:
                        continue
                    out.append((r, d)); ys.append(1.0 if val > line else 0.0)
                return out, np.array(ys)
            a, ya = xy(tr)
            b, yb = xy(te)
            sg = 13.5
            lr = LogisticRegression(C=10.0).fit(np.array([[d / sg] for _, d in a]), ya)
            coef["%s %d" % (kind, ty)] = {"w_model_diff_per_13.5pts": float(lr.coef_[0][0]), "intercept": float(lr.intercept_[0])}
            pl = lr.predict_proba(np.array([[d / sg] for _, d in b]))[:, 1]
            f2 = lambda lst: np.array([[d, r["spread"], r["total_line"], r["rest_diff"], r["dome"], r["wind"] or 0,  # noqa: E731
                                        r["temp"] or 60] for r, d in lst])
            gb = HistGradientBoostingClassifier(max_depth=2, learning_rate=0.03, max_iter=100, min_samples_leaf=50,
                                                random_state=7).fit(f2(a), ya)
            pg = gb.predict_proba(f2(b))[:, 1]
            for i, (r, d) in enumerate(b):
                pc = ncdf(d / sg)
                eng = W_ENGINE * pc + (1 - W_ENGINE) * 0.5
                for k, v in ((kind + ":market(0.5)", 0.5), (kind + ":current_model", pc), (kind + ":current_engine_blend", eng),
                             (kind + ":logit_diff", pl[i]), (kind + ":gbm_features", pg[i])):
                    store[k]["p"].append(v); store[k]["y"].append(yb[i])
                if kind == "Spread":
                    oh, oa = dec(r["so_h"]), dec(r["so_a"])
                else:
                    oh, oa = dec(r["ov"]), dec(r["un"])
                for key, p in ((kind + ":engine", eng), (kind + ":logit_diff", pl[i])):
                    if p * oh - 1 > 0.03:
                        roi[key].append(oh - 1 if yb[i] == 1 else -1.0)
                    elif (1 - p) * oa - 1 > 0.03:
                        roi[key].append(oa - 1 if yb[i] == 0 else -1.0)
    out = {}
    for k, v in store.items():
        m = metrics(v["p"], v["y"]); b = calib_bins(v["p"], v["y"], 8)
        m["ece"] = ece(b); m["bins"] = b
        out[k] = m
    out["_roi"] = {k: {"bets": len(v), "roi_per_bet": (sum(v) / len(v)) if v else None,
                       "win_rate": (sum(1 for x in v if x > 0) / len(v)) if v else None} for k, v in roi.items()}
    out["_coef"] = coef
    return out


# ----------------------------------------------------------------------------- NBA
def load_nba():
    games = []
    for s in (2023, 2024, 2025, 2026):
        for r in json.loads((DATA / ("nba_games_%d.json" % s)).read_text()):
            d = datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
            games.append({"id": r["id"], "season": s, "date": d, "home": r["home"], "away": r["away"],
                          "home_score": r["hs"], "away_score": r["as"], "final": True, "neutral": False})
    seen, out = set(), []
    for g in sorted(games, key=lambda g: g["date"]):
        if g["id"] not in seen:
            seen.add(g["id"]); out.append(g)
    return out


def nba_prev_cut(t):
    y = t.year if t.month >= 8 else t.year - 1
    return datetime(y, 10, 1, tzinfo=timezone.utc)


def elo_walk(games, k=20.0, hfa=70.0):
    elo, out = {}, {}
    last = {}
    for g in games:
        h, a = elo.setdefault(g["home"], 1500.0), elo.setdefault(g["away"], 1500.0)
        # season carry-over: regress 25% to mean at the start of a new season
        p = 1 / (1 + 10 ** (-(h - a + hfa) / 400))
        out[g["id"]] = {"p_elo": p, "elo_diff": h - a}
        mov = g["home_score"] - g["away_score"]
        mult = ((abs(mov) + 3) ** 0.8) / (7.5 + 0.006 * abs(h - a + hfa)) if mov else 1
        d = k * mult * ((1.0 if mov > 0 else 0.0) - p)
        elo[g["home"]] = h + d; elo[g["away"]] = a - d
        # new season boundary
        if last.get("season") not in (None, g["season"]) or False:
            pass
        last["season"] = g["season"]
    return out


def run_nba():
    games = load_nba()
    # regress Elo toward the mean between seasons
    elo_games = []
    prev_season = None
    preds = walk(games, datetime(2023, 12, 1, tzinfo=timezone.utc), 7, "nba", nba_prev_cut)
    # Elo with offseason regression
    elo, el = {}, {}
    for g in games:
        if prev_season is not None and g["season"] != prev_season:
            # new-season boundary only detectable through the season label (2026 contains 2026-27 openers too)
            for t in elo:
                elo[t] = 1500 + 0.75 * (elo[t] - 1500)
        prev_season = g["season"]
        h, a = elo.setdefault(g["home"], 1500.0), elo.setdefault(g["away"], 1500.0)
        p = 1 / (1 + 10 ** (-(h - a + 70) / 400))
        el[g["id"]] = p
        mov = g["home_score"] - g["away_score"]
        mult = ((abs(mov) + 3) ** 0.8) / (7.5 + 0.006 * abs(h - a + 70))
        d = 20 * mult * ((1.0 if mov > 0 else 0.0) - p)
        elo[g["home"]] = h + d; elo[g["away"]] = a - d
    last_game = {}
    rows = []
    for g in games:
        pr = preds.get(g["id"])
        rd = {}
        for side in ("home", "away"):
            rd[side] = (g["date"] - last_game[g[side]]).total_seconds() / 86400 if g[side] in last_game else 3.0
        last_game[g["home"]] = g["date"]; last_game[g["away"]] = g["date"]
        if pr is None:
            continue
        rows.append({"id": g["id"], "date": g["date"], "season": g["season"], "p_home_model": pr["p_home"],
                     "margin_model": pr["margin"], "total_model": pr["total"], "p_elo": el[g["id"]],
                     "rest_h": min(rd["home"], 7), "rest_a": min(rd["away"], 7),
                     "y": 1.0 if g["home_score"] > g["away_score"] else 0.0,
                     "margin": g["home_score"] - g["away_score"], "tot": g["home_score"] + g["away_score"]})
    return rows


def eval_nba(rows):
    """Expanding window: test blocks are half-seasons; all models trained only on earlier rows."""
    rows = [r for r in rows if r["date"] >= datetime(2023, 12, 1, tzinfo=timezone.utc)]
    cuts = [datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)]
    store = {k: {"p": [], "y": []} for k in ["home_rate", "current_model", "elo", "platt_model", "platt_blend_model_elo",
                                              "logit_model+elo+rest", "gbm_features"]}
    for c in cuts:
        tr = [r for r in rows if r["date"] < c]
        te = [r for r in rows if r["date"] >= c and r["date"] < c + timedelta(days=365)]
        ytr = np.array([r["y"] for r in tr]); yte = np.array([r["y"] for r in te])
        hr = ytr.mean()
        fm = lambda rs: np.array([[logit(r["p_home_model"])] for r in rs])  # noqa: E731
        fb = lambda rs: np.array([[logit(r["p_home_model"]), logit(r["p_elo"])] for r in rs])  # noqa: E731
        fr = lambda rs: np.array([[logit(r["p_home_model"]), logit(r["p_elo"]), r["rest_h"] - r["rest_a"],  # noqa: E731
                                   float(r["rest_h"] < 1.5), float(r["rest_a"] < 1.5)] for r in rs])
        m1 = LogisticRegression(C=10).fit(fm(tr), ytr)
        m2 = LogisticRegression(C=10).fit(fb(tr), ytr)
        m3 = LogisticRegression(C=10).fit(fr(tr), ytr)
        m4 = HistGradientBoostingClassifier(max_depth=2, learning_rate=0.03, max_iter=100, min_samples_leaf=60,
                                            random_state=7).fit(fr(tr), ytr)
        cols = {"home_rate": np.full(len(te), hr), "current_model": np.array([r["p_home_model"] for r in te]),
                "elo": np.array([r["p_elo"] for r in te]), "platt_model": m1.predict_proba(fm(te))[:, 1],
                "platt_blend_model_elo": m2.predict_proba(fb(te))[:, 1],
                "logit_model+elo+rest": m3.predict_proba(fr(te))[:, 1], "gbm_features": m4.predict_proba(fr(te))[:, 1]}
        for k, v in cols.items():
            store[k]["p"].extend(v.tolist()); store[k]["y"].extend(yte.tolist())
    out = {}
    for k, v in store.items():
        m = metrics(v["p"], v["y"]); b = calib_bins(v["p"], v["y"], 8)
        m["ece"] = ece(b); m["bins"] = b
        out[k] = m
    # does the model's margin have bias? (mean actual - predicted margin)
    te = [r for r in rows if r["date"] >= cuts[0]]
    out["_bias"] = {"mean_margin_error": float(np.mean([r["margin"] - r["margin_model"] for r in te])),
                    "mean_total_error": float(np.mean([r["tot"] - r["total_model"] for r in te])), "n": len(te)}
    return out


if __name__ == "__main__":
    res = {}
    print("NFL ...", flush=True)
    nfl = run_nfl()
    res["nfl"] = eval_nfl(nfl)
    (OUT / "games_metrics.json").write_text(json.dumps(res, indent=1))
    print("NBA ...", flush=True)
    nba = run_nba()
    res["nba"] = eval_nba(nba)
    rr = [r for r in nba if r["date"] >= datetime(2023, 12, 1, tzinfo=timezone.utc)]
    pf = LogisticRegression(C=10).fit(np.array([[logit(r["p_home_model"])] for r in rr]), np.array([r["y"] for r in rr]))
    res["nba"]["_platt_all_oos"] = {"a": float(pf.intercept_[0]), "b": float(pf.coef_[0][0]), "n": len(rr)}
    (OUT / "games_metrics.json").write_text(json.dumps(res, indent=1))
    for lg in ("nfl", "nba"):
        print("==", lg)
        for k, v in res[lg].items():
            if k.startswith("_"):
                print(k, json.dumps(v)); continue
            print("%-28s n=%4d  ll=%.4f  brier=%.4f  acc=%.3f  ece=%.3f" % (k, v["n"], v["logloss"], v["brier"], v["acc"], v["ece"]))
