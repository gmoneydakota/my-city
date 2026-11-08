---
title: Improve the self-learning betting model
tags: bets, nfl, nba, calibration, walk-forward, learning
agents: quant, coder
learned_from: 2, 6, 26
related: stock-signal-model, factor-edge-test
---
## When to use
Changes to the Lucky Tower model in `bets/`, or measuring whether it is any good.

## How
1. Read what it has learned: `bets/learned.json`, `bets/history/learning_log.json`, graded results in `bets/history/*.csv` (`shadow_bets.csv` has the graded rows).
2. Test ideas walk-forward (fit on the past, test on the next period) like job 6's accuracy lab. Report calibration, not just win rate.
3. **Bucket by market-implied probability before blaming the model.** Group graded bets by the implied probability of the price (under 10%, 10-20%, 20-30%...) and compare model p, market-implied p and actual win rate per bucket. Job 22 found the model floored every long shot at about 10% while long shots won 5.5%. The average looked fine; the bucket did not.
4. Check for one-sided markets. Some props (e.g. NFL `anytime_td`) post only a "yes" price, so there is no two-way market to remove the vig from. Then the model runs alone, and the learned prop weight never applies. Fix: fair = implied x (1 - hold), with the hold as a named constant (`ONE_SIDED_HOLD` in `bets/betmodel/engine.py`), blended with the model by the learned weight.
5. Change `bets/betmodel/`, add a test to `bets/test_betmodel.py`, run `cd bets && python3 test_betmodel.py`.
6. Never edit `bets/history/` or `learned.json`; the daily learner owns them.

## Gotchas
- With thin data, the right change is often no change plus a short report. Job 22 changed one thing (one-sided props) and left NBA overs and the other markets alone: fewer than 50 graded rows each.
- Two days of graded rows is not a trend. Say so and set a date to re-check the bucket that moved.
- Hold figures (e.g. 10%) are typical values, not measured. Write them in the README as assumptions.
- Before testing a new factor for an edge, run it through `factor-edge-test` (break-even and standard error).
