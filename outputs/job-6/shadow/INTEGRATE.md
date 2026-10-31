# Wiring the shadow module into `bets/` (shadow mode only)

Nothing here has been applied. The owner applies it through a separate upgrade.

1. Copy `shadow_model.py` to `bets/betmodel/shadow.py`. Install `numpy scipy scikit-learn` only if you want the ridge part;
   the market-weight and NBA blend functions are stdlib-only.
2. Feature flag: `LUCKY_SHADOW=1` (env var). When off, do nothing.
3. In `engine.game_bets()`, after the current `p_blend` is computed for each bet, if flag on also compute:
   - NFL moneyline: `shadow.nfl_ml_prob(spread_line)` shrunk with `shadow.shrink_to_market(p_model, p_mkt, shadow.market_weight("nfl","ml"))`
   - NFL spread / total: `p = p_market` (model weight 0)
   - NBA moneyline: `shadow.nba_ml_prob(p_model, p_elo, rest_h, rest_a)` (refit `fit_nba_blend` on graded history first)
4. In `engine.prop_bets()` for NFL passing stats (pass_yds, pass_att, completions): build the 8 features in `RidgeDist.FEATS`
   (EWMA 3/6/20 of the player's stat, last-3 mean, games played, team implied points, home flag, opponent allowance ratio),
   train `RidgeDist` on the player history you already log in `history/projections_log.csv`, and log `p_over` as the shadow value.
5. Log both: append rows to `history/shadow_bets.csv` (existing `learn.SHADOW` file) with columns `model` = `current` / `shadow`,
   the probability, and the line. `learn.grade()` already grades that file; compare log loss per bet type after >= 1 week
   (and realistically a few hundred graded bets per category; a week is too few for props).
6. "What it learned" text: add one line per bet type, e.g. "Shadow model vs current on N graded bets: log loss X vs Y".
7. Do not touch the Odds API credit logic. Do not let shadow picks reach the board until the live comparison agrees with the backtest.

`CONF_FLOOR` in the module is a starting guess, not a backtest-derived value. Replace it once you have live graded data.
