"""Current factor sheet: last-8-game points for/against (shrunk vs league) for teams on the slate.
Run: python3 outputs/job-21/current_factors.py   (uses job-6 cached data; NFL through 2026 wk, NBA 2025-26 season file)"""
import json, pandas as pd, numpy as np

d = pd.read_csv("outputs/job-6/data/nfl_games.csv")
d = d[d.home_score.notna()].sort_values("gameday")
cur = d[d.season == d.season.max()]
print("NFL last played:", cur.gameday.max(), "season", d.season.max())
def team(df, t, hc, ac, hs, as_, n=8):
    rows = []
    for _, g in df.iterrows():
        if g[hc] == t: rows.append((g[hs], g[as_]))
        elif g[ac] == t: rows.append((g[as_], g[hs]))
    r = rows[-n:]
    return len(rows), np.mean([a for a, _ in r]), np.mean([b for _, b in r])
out = {}
lg = np.mean(list(cur.home_score) + list(cur.away_score))
print("NFL league avg ppg", round(lg, 1))
for t in ["PHI", "WAS", "CHI", "SEA"]:
    n, pf, pa = team(cur, t, "home_team", "away_team", "home_score", "away_score")
    out[t] = dict(games=n, pf=round(pf, 1), pa=round(pa, 1)); print(t, out[t])
nb = json.load(open("outputs/job-6/data/nba_games_2026.json"))
nb = [g for g in nb if g.get("hs") is not None]
nb = pd.DataFrame(nb)
lgn = np.mean(list(nb.hs) + list(nb["as"]))
print("NBA league avg", round(lgn, 1), "games", len(nb), "through", nb.date.max())
for t in ["LAC", "GS", "TOR", "LAL"]:
    n, pf, pa = team(nb, t, "home", "away", "hs", "as")
    out[t] = dict(games=n, pf=round(pf, 1), pa=round(pa, 1)); print(t, out[t])
json.dump(out, open("outputs/job-21/current_factors.json", "w"), indent=1)
