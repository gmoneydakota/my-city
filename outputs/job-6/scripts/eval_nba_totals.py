"""NBA game-total test (walk-forward) on the cached ESPN team games.

No NBA market totals or player box scores are cached, so this compares model-vs-model only:
  A  league running mean of total points
  B  each team's running average points scored/allowed (pace-neutral blend), shrunk to league mean
  C  B + back-to-back / rest adjustment
Error = MAE of predicted total, plus bias. P(over) is scored against a PROXY line (average of both
teams' trailing-10-game totals), so this is not a market test.
Run: python3 outputs/job-6/scripts/eval_nba_totals.py
"""
import json
import math
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
games = []
for s in (2023, 2024, 2025, 2026):
    p = ROOT / "data" / ("nba_games_%d.json" % s)
    if p.exists():
        games += json.loads(p.read_text())
games = [g for g in games if g.get("hs") is not None and g.get("as") is not None]
games.sort(key=lambda g: g["date"])
SHR = 15  # games of shrinkage toward league mean
K = 10

lg_sum = lg_n = 0
pf, pa, n = defaultdict(float), defaultdict(float), defaultdict(int)
last = {}
tot_hist = defaultdict(lambda: deque(maxlen=K))
rows = []
for g in games:
    h, a = g["home"], g["away"]
    d = datetime.strptime(g["date"][:10], "%Y-%m-%d")
    tot = g["hs"] + g["as"]
    if lg_n > 600 and n[h] >= 15 and n[a] >= 15 and len(tot_hist[h]) >= 5 and len(tot_hist[a]) >= 5:
        mu = lg_sum / lg_n / 2  # per-team league mean

        def r(t, arr):
            return (arr[t] + SHR * mu) / (n[t] + SHR)
        B = r(h, pf) + r(a, pa) + r(a, pf) + r(h, pa)
        B = B / 2 + 0  # avg of the two matchup views, each side = scoring + opp allowing
        rest = lambda t: (d - last[t]).days if t in last else 3
        b2b = (rest(h) <= 1) + (rest(a) <= 1)
        C = B - 1.2 * b2b
        proxy = (np.mean(tot_hist[h]) + np.mean(tot_hist[a])) / 2
        rows.append(dict(season=g["date"][:4], A=2 * mu, B=B, C=C, proxy=proxy, y=tot))
    lg_sum += tot
    lg_n += 1
    pf[h] += g["hs"]; pa[h] += g["as"]; n[h] += 1
    pf[a] += g["as"]; pa[a] += g["hs"]; n[a] += 1
    last[h] = last[a] = d
    tot_hist[h].append(tot); tot_hist[a].append(tot)

y = np.array([r["y"] for r in rows])
res = {"n": len(rows), "note": "no market totals cached for NBA; proxy line = mean of both teams' trailing-10 totals"}
for k in ("A", "B", "C", "proxy"):
    p = np.array([r[k] for r in rows])
    res["mae_" + k] = float(np.mean(np.abs(p - y)))
    res["bias_" + k] = float(np.mean(p - y))
# P(over proxy) with normal sd from first half (train), scored on second half
half = len(rows) // 2
resid = y[:half] - np.array([r["C"] for r in rows])[:half]
sd = float(resid.std())
def ncdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
pov = np.array([1 - ncdf((r["proxy"] + 0.0 - r["C"]) / sd) for r in rows])  # P(actual > proxy) under model C
over = (y > np.array([r["proxy"] for r in rows])).astype(float)
pt, ot = np.clip(pov[half:], 1e-3, 1 - 1e-3), over[half:]
res["proxy_over_logloss_C"] = float(-np.mean(ot * np.log(pt) + (1 - ot) * np.log(1 - pt)))
res["proxy_over_logloss_naive50"] = 0.6931
res["sd_total"] = sd
out = ROOT / "results" / "nba_extra.json"
out.write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
