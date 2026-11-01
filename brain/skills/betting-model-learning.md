---
title: Improve the self-learning betting model
tags: bets, nfl, nba, calibration, walk-forward, learning
agents: quant, coder
learned_from: 2, 6
related: stock-signal-model
---
## When to use
Changes to the Lucky Tower model in `bets/`, or measuring whether it is any good.

## How
1. Read what it has learned: `bets/learned.json`, `bets/history/learning_log.json`, graded results in `bets/history/*.csv`.
2. Test ideas walk-forward (fit on the past, test on the next period) like job 6's accuracy lab. Report calibration, not just win rate.
3. Change `bets/betmodel/`, add a test to `bets/test_betmodel.py`, run `cd bets && python3 test_betmodel.py`.
4. Never edit `bets/history/` or `learned.json`; the daily learner owns them.

## Gotchas
- With thin data, the right change is often no change plus a short report.
