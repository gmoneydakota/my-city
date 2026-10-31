# Report: can Lucky Tower's probabilities be made more honest?

Data as of 31 Oct 2026. All tests are walk-forward (train on earlier seasons, test on a later one). Numbers come from
`results/games_metrics.json`, `results/props_metrics.json`, `results/nba_extra.json`. Lower log loss / Brier is better; a coin flip is 0.693 / 0.250.

## Data
- NFL: nflverse games with closing moneyline/spread/total (1999-2026; tests use 2022-2025), nflverse player-weeks 2020-2026 (QB/RB/WR/TE).
- NBA: ESPN team game results 2023-2026 (about 4,400 games). **No NBA market lines and no NBA player box scores are cached.**
- Not collected: injuries, weather beyond nflverse temp/wind, referees, snap/route data, DraftKings prop history. Real historical
  prop lines are not free, so **prop "lines" in these tests are a proxy: the player's trailing 8-game median, rounded to x.5.**
  Beating that proxy is NOT the same as beating DraftKings.

## Old vs new, by bet type (out of sample)

| Bet type | n | Current model | Best alternative | Verdict |
|---|---|---|---|---|
| NFL moneyline (log loss) | 1084 | 0.6456 (Brier 0.227) | Market from spread 0.6068 (Brier 0.210); de-vigged ML 0.6082; current engine blend 0.6145 | **Market wins clearly.** Current model hurts. |
| NFL spread (vs 50% at the line) | 1058 | 0.7189 | Market 0.6931; best model 0.6943 | No model beats the closing line. Betting the engine's spread picks: 271 bets, -2.6% ROI/bet |
| NFL total | 1079 | 0.7149 | Market 0.6931; best model 0.6950 | Same. Engine total picks: 250 bets, -2.3% ROI/bet |
| NBA moneyline (no market data) | 2469 | 0.6054 | Logit(team model + elo + rest) 0.6000 (Brier 0.2068) | Small gain (about 0.005). Plausible, not proven vs a market |
| NBA total | 4403 | n/a | Trailing-10 team totals MAE 15.0 vs season-rating model 15.5 | Recent form beat season ratings; no market line to test. Rest/back-to-back tweak did not help (it increased bias) |
| NFL passing yards | 1550 | 0.6833 | Ridge + gamma 0.6605 | **New wins** (proxy line) |
| NFL pass attempts | 1576 | 0.6883 | Ridge + neg-binomial 0.6608 | **New wins** (proxy line) |
| NFL completions | 1574 | 0.6981 (worse than coin flip) | 0.6705 | **New wins** (proxy line) |
| NFL rush yards | 2410 | 0.6752 | Current + Platt 0.6632 | Recalibrating current is enough |
| NFL rush attempts | 1987 | 0.6583 | Ridge 0.6520 | Small gain |
| NFL receptions | 7189 | 0.6555 | Platt 0.6524 / ridge 0.6526 | Tie |
| NFL receiving yards | 5743 | 0.6830 | Current + Platt 0.6682 | Recalibrating current is enough |
| NBA player props | 0 | not tested | not tested | No player box-score data cached; fetching ~1,200 box scores/season from ESPN exceeded this job's budget. |

## What it means in plain English
1. **For NFL sides and totals, trust the closing line.** Our team model adds nothing, and its weight in the learned blend should be near zero. The
   fitted logistic put a negative weight on the model's margin for moneylines (-0.56 to -0.84), i.e. its disagreement with the market has been wrong, not just noisy.
2. **The "mostly unders" issue is partly real, partly a calibration problem.** The current passing projections run **high** (pass yards +6.7 too high on average; attempts +1.1, completions +0.7),
   which would produce *overs*, yet 72-88% of its strong calls were unders - because its spread is too narrow in some stats and the probability mapping is off.
   Rushing and receiving yards run low (-2 to -5.6 per player; RBs worst at -5.6 receiving yards), which produces unders that look strong but are inflated. The ridge model
   removes bias (mean error about 0 for every stat) and gives balanced over/under claims. Its strong unders hit 64-67% when it claimed ~68%: close, slightly overconfident.
3. **Calibration matters more than accuracy here.** Current "strong" over claims of ~65% hit 57-62% for yards props. After Platt scaling or the ridge model they hit about 60-66%.
4. **NBA:** team ratings alone are decent (66.8% accuracy); adding elo and rest gives a small log-loss gain. Without market lines, this cannot show a betting edge.
5. **CLV:** not measurable. No closing-line history for props or NBA. Treat CLV as unmeasured, not positive.

## Limitations
- Prop lines are a proxy (trailing 8-game median). A real book line includes injuries, matchup and news; the true gap to DraftKings is unknown and probably smaller.
- Log loss gains on proxy lines mostly reflect better mean/variance estimates than a median rule, not a market edge.
- Only 4 NFL test seasons; per-stat n is large for yards but small for the NBA split.
- No injury, weather (beyond nflverse), referee or snap-share features were added; no LightGBM (sklearn gradient boosting was tried and lost to simpler models on games).
- Hierarchical/Bayesian shrinkage was approximated only by the ridge + EWMA priors, not a full model.
- Confidence floors in `shadow/` are starting guesses. The live one-week shadow run has not happened.

## Calibration
Reliability bins (predicted vs observed) are saved in `results/*.json` under `bins` for each model. Market moneyline ECE 0.018-0.022; current model 0.054.
No PNG plots were generated in this attempt (plotting libraries were not part of the minimal run).

## Features that mattered
For props: EWMA of the player's own recent output (half-lives 3/6/20 games), team implied points, opponent allowance ratio. For NFL games: the market spread; nothing else added value.

## Top 5 next experiments
1. Get real historical prop lines (paid/archived feeds, or start logging DraftKings lines daily now) and re-run the prop tests against them; add CLV.
2. Fetch NBA player box scores and run the NBA points/rebounds/assists/threes tests with the same ridge + distribution recipe.
3. Add injury/inactive status and snap-share/target-share as features (the biggest missing context); test usage redistribution when a starter is out.
4. Run the shadow module live for 4+ weeks and compare on graded bets per category before replacing anything.
5. Fit a proper hierarchical model for low-sample players (rookies, backups) and a market-anchored NBA total/spread model once NBA closing lines are cached.

This is an educational model, not financial advice. Markets can move against any signal.
