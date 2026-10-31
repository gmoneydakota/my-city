# Job 6 progress (attempt 2)

## How the existing Lucky Tower model works (read from `bets/betmodel/`)
- `ratings.py` `TeamModel`: team ratings fit from past results (margin-based, home advantage, rest), turned into win
  probability / expected margin / expected total. Used for moneyline, spread, total.
- `engine.py`: for each game bet, blends model probability with the de-vigged market probability using a weight `w`
  (`game_weight()` from `learned.json`), then computes edge/EV vs the DraftKings price. Props use `props.py`
  (`project()` -> mean + spread per player/stat from recent game logs, `model_probs()` -> over/under probability) and
  `prop_weight()`. Underdog legs are compared to break-even and combined into entries (`best_entries`).
- `learn.py`: `record()` stores every priced bet + projection, `grade()` fills results when games finish, `fit()` retunes
  the model-vs-market weights (log-loss, shrunk toward defaults) and per-stat projection/spread scales; writes `learned.json`.
- Known issue from the request: most top props are unders.

## Status
- [x] Step 1 data: NFL games+odds 1999-2026 (`nfl_games.csv`), NFL player-weeks 2020-2026, NBA team games 2023-2026
      (ESPN). Cached in `data/`. NOT re-downloaded.
- [x] Step 2/3 game-level walk-forward tests (`results/games_metrics.json`) and NFL prop tests (`results/props_metrics.json`).
- [x] README, REPORT (this attempt)
- [x] NBA totals test and NBA props feasibility (see REPORT)
- [x] `shadow/` module + `INTEGRATE.md`
- [ ] NOT done: live shadow-mode week (needs the owner to apply integration), injuries/weather/referee features, NBA player
      box-score data, real historical prop lines, CLV (no closing-line history for props).
