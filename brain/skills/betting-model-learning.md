---
title: Improve the self-learning betting model
tags: bets, nfl, nba, calibration, walk-forward, learning
agents: quant, coder
learned_from: 2, 6, 22, 26, 27, 33
related: stock-signal-model, factor-edge-test
---
## When to use
Changes to the Lucky Tower model in `bets/`, or measuring whether it is any good.

## How
1. Read what it has learned: `bets/learned.json`, `bets/history/learning_log.json`, and the graded rows in `bets/history/shadow_bets.csv` (other graded results sit in `bets/history/*.csv`).
2. Test ideas walk-forward (fit on the past, test on the next period) like job 6's accuracy lab. Report calibration, not just win rate.
3. **Bucket by market-implied probability before blaming the model.** Group graded bets by the implied probability of the price (under 10%, 10-20%, 20-30%...) and compare model p, market-implied p and actual win rate per bucket. Job 22 found the model floored every long shot at about 10% while long shots won 5.5%. The average looked fine; the bucket did not.
4. **Split two-way props by side.** Group graded over/under pairs by side and compare each side's win rate and ROI with its implied probability. Job 27 counted 1,237 pairs: overs won 43.2% where the price implied 49.3%, and unders won. The gap held in both sports, both halves of the window and every probability bucket, so it was not noise. Check the market's own de-vigged probability too: if it carries the same bias, blending with it will not remove the gap.
5. Check for one-sided markets. Some props (e.g. NFL `anytime_td`) post only a "yes" price, so there is no two-way market to remove the vig from. Then the model runs alone, and the learned prop weight never applies. Fix: fair = implied x (1 - hold), with the hold as a named constant (`ONE_SIDED_HOLD` in `bets/betmodel/engine.py`), blended with the model by the learned weight.
6. Change `bets/betmodel/`, add a test to `bets/test_betmodel.py`, run `cd bets && python3 test_betmodel.py`.
7. Never edit `bets/history/` or `learned.json`; the daily learner owns them.

## Gotchas
- With thin data, the right change is often no change plus a short report. Job 22 changed one thing (one-sided props) and left NBA overs and the other markets alone: fewer than 50 graded rows each.
- A side-bias fix (step 4) should be about half the observed gap, written as a named constant, with a date to re-check it and a rule for raising or dropping it. Half the gap is a judgement, not a fit; say so.
- Two days of graded rows is not a trend. Say so and set a date to re-check the bucket that moved.
- Hold figures (e.g. 10%) are typical values, not measured. Write them in the README as assumptions.
- Before you report a change as made, grep for its constant or function name in `bets/betmodel/`. A job's own README can describe code that is not in the files.
- Check a gap's weekly trend before sizing a fix (job 33: over gap 8.2 -> 1.5 pts over four weeks). `pip install pandas numpy` is needed for ad-hoc analysis on the runner.
- Before testing a new factor for an edge, run it through `factor-edge-test` (break-even and standard error).
