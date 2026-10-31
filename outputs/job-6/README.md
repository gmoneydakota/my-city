# Job 6: Lucky Tower accuracy lab

Walk-forward tests of whether the Lucky Tower betting model can be made better calibrated, and a drop-in shadow module.

| Path | What |
|---|---|
| `REPORT.md` | Findings: old-vs-new table per bet type, plain-English meaning, limits, next experiments |
| `PROGRESS.md` | How the current model works, what is done / not done |
| `data/` | Cached history: NFL games + closing lines, NFL player-weeks 2020-26, NBA team games 2023-26 (ESPN) |
| `scripts/fetch_data.py` | Downloads data (skips files already present) |
| `scripts/eval_games.py` | Moneyline / spread / total tests, NFL + NBA -> `results/games_metrics.json` |
| `scripts/eval_props.py` | NFL player-prop tests -> `results/props_metrics.json` |
| `scripts/eval_nba_totals.py` | NBA totals + NBA prop feasibility -> `results/nba_extra.json` |
| `shadow/` | `shadow_model.py` + `INTEGRATE.md` for running the new logic beside the current model |

Run (needs `pip install numpy pandas scikit-learn`; seeds are fixed):
```
python3 outputs/job-6/scripts/eval_games.py
python3 outputs/job-6/scripts/eval_props.py
python3 outputs/job-6/scripts/eval_nba_totals.py
python3 outputs/job-6/shadow/shadow_model.py     # self-test
```
Nothing outside `outputs/job-6/` was changed. This is an educational model, not financial advice.
