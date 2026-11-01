"""Do weather / defense / rest factors beat the NFL closing line? Walk-forward test.

Data: outputs/job-6/data/nfl_games.csv (nflverse, closing lines, temp, wind, roof).
Method: for every game compute factors known BEFORE kickoff, regress the market's miss
(total - total_line, or result - spread_line) on them using only EARLIER seasons, then
bet the sign of the prediction when it is big enough, on the test season. Report vs 52.4% break-even.
Run: python3 outputs/job-21/factor_backtest.py
"""
import json, numpy as np, pandas as pd
from collections import defaultdict, deque

d = pd.read_csv("outputs/job-6/data/nfl_games.csv")
d = d[(d.season >= 2012) & d.home_score.notna() & d.total_line.notna()].sort_values(["gameday", "game_id"]).reset_index(drop=True)

# ---- rolling team form (points for/against vs league avg, last 8 games, shrunk), no look-ahead
hist = defaultdict(lambda: deque(maxlen=8))
rows = []
for _, g in d.iterrows():
    h, a = g.home_team, g.away_team
    def form(t):
        x = hist[t]
        n = len(x)
        if n == 0:
            return 0.0, 0.0, 0
        pf = np.mean([p for p, _ in x]); pa = np.mean([q for _, q in x])
        k = n / (n + 4.0)  # shrink toward league average (0 = avg)
        return k * (pf - 22.5), k * (pa - 22.5), n
    hpf, hpa, hn = form(h); apf, apa, an = form(a)
    rows.append(dict(hpf=hpf, hpa=hpa, apf=apf, apa=apa, n=min(hn, an)))
    hist[h].append((g.home_score, g.away_score)); hist[a].append((g.away_score, g.home_score))
f = pd.concat([d, pd.DataFrame(rows)], axis=1)
f = f[f.n >= 4]

dome = f.roof.isin(["dome", "closed"])
f["wind15"] = ((f.wind.fillna(0) >= 15) & ~dome).astype(float)
f["wind10"] = np.where(dome, 0, f.wind.fillna(0).clip(0, 30))
f["cold"] = np.where(dome, 0, (45 - f.temp.fillna(60)).clip(0, 40))  # degrees below 45F
f["dome"] = dome.astype(float)
f["def_sum"] = f.hpa + f.apa           # both defenses' points allowed above avg (+ = bad defenses)
f["off_sum"] = f.hpf + f.apf
f["def_diff"] = f.apa - f.hpa          # + = away defense worse than home -> home edge
f["off_diff"] = f.hpf - f.apf
f["rest_diff"] = (f.home_rest - f.away_rest).clip(-4, 4)
f["div"] = f.div_game.astype(float)
f["miss_total"] = f.total - f.total_line
f["miss_spread"] = f.result - f.spread_line   # result = home margin; spread_line = home expected margin
f["thu"] = (f.weekday == "Thursday").astype(float)

def ols(X, y, lam=50.0):
    X1 = np.c_[np.ones(len(X)), X]
    P = np.eye(X1.shape[1]) * lam; P[0, 0] = 0
    return np.linalg.solve(X1.T @ X1 + P, X1.T @ y)

def run(name, target, feats, push_col, thresh_pts, sign_over):
    out = []
    for season in range(2018, 2026):
        tr = f[f.season < season]; te = f[f.season == season]
        b = ols(tr[feats].values, tr[target].values)
        pred = np.c_[np.ones(len(te)), te[feats].values] @ b
        out.append(te.assign(pred=pred))
    o = pd.concat(out)
    bet = o[(o.pred.abs() >= thresh_pts) & (o[target] != 0)]
    win = ((np.sign(bet.pred) == np.sign(bet[target]))).mean() if len(bet) else float("nan")
    allr = np.corrcoef(o.pred, o[target])[0, 1]
    # coefficients on full data
    b = ols(f[feats].values, f[target].values)
    return dict(name=name, n_test=int(len(o)), corr_pred_vs_market_miss=round(float(allr), 4), bets=int(len(bet)),
                win_rate=round(float(win), 4), breakeven=0.5238,
                roi_at_minus110=round(float(win * 0.9091 - (1 - win)), 4) if len(bet) else None,
                coef={k: round(float(v), 3) for k, v in zip(["intercept"] + feats, b)})

res = []
res.append(run("TOTAL: weather only", "miss_total", ["wind10", "cold", "dome"], None, 1.0, True))
res.append(run("TOTAL: defenses+offenses form", "miss_total", ["def_sum", "off_sum"], None, 1.0, True))
res.append(run("TOTAL: weather+form+rest/div", "miss_total", ["wind10", "cold", "dome", "def_sum", "off_sum", "div", "thu"], None, 1.0, True))
res.append(run("SPREAD: defense/offense gap + rest", "miss_spread", ["def_diff", "off_diff", "rest_diff"], None, 0.75, False))
res.append(run("SPREAD: all factors", "miss_spread", ["def_diff", "off_diff", "rest_diff", "div", "thu", "wind10", "cold"], None, 0.75, False))

# simple, rule-style checks that a bettor would actually use
rules = {}
def rule(label, mask, col="miss_total"):
    g = f[mask & (f.season >= 2018)]
    if col == "miss_total":
        g = g[g.miss_total != 0]; r = (g.miss_total < 0).mean()   # share of UNDERs
        rules[label] = dict(n=int(len(g)), under_rate=round(float(r), 4), avg_miss_pts=round(float(g.miss_total.mean()), 2))
rule("wind >=15 mph, outdoors", f.wind15 == 1)
rule("wind >=20 mph, outdoors", (f.wind >= 20) & ~dome)
rule("temp <=32F, outdoors", (f.temp <= 32) & ~dome)
rule("dome / closed roof", dome)
rule("both defenses strong (def_sum <= -2)", f.def_sum <= -2)
rule("both defenses weak (def_sum >= +2)", f.def_sum >= 2)
rule("all games (baseline)", f.season >= 0)
json.dump(dict(models=res, rules=rules), open("outputs/job-21/backtest_results.json", "w"), indent=1)
for r in res: print(r["name"], "| bets", r["bets"], "| win", r["win_rate"], "| corr", r["corr_pred_vs_market_miss"]); print("   ", r["coef"])
print(json.dumps(rules, indent=1))
