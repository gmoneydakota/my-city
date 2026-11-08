---
title: Test whether a factor beats the market line
tags: betting, backtest, walk-forward, break-even, statistics, market, factors
agents: quant, coder, analyst
learned_from: 26
related: betting-model-learning, stock-signal-model
---
## When to use
Someone asks "does weather / rest / form / a signal predict the result?" before any bet or model change. Job 21 used it on 2,310 NFL games.

## How
1. Build the dataset: one row per game (or per trade), with the factor values known *before* the event and the closing line or price. Use history only, and no same-day data.
2. Walk-forward: for each season (or period), fit any coefficients on earlier periods only, then bet the next one. Never score a model on the data it was fit on.
3. Compute the break-even win rate: at American odds -110 it is 110/210 = **52.4%**; generally, implied = 1/decimal odds. Compare the win rate with it, not with 50%.
4. Compare with the baseline: the same rule on all games (job 21: 51.2% under as the baseline, not 50%).
5. Give each result n and a standard error: SE = sqrt(p(1-p)/n). A rule at 57% with n=159 is about 1.8 SE from 50%.
6. Verdict: "edge" only if out-of-sample win rate beats break-even by about 2 SE with a stated reason. Otherwise write "no edge" and keep the rule as a *possible* lean.
7. Save `backtest_results.json` and the script next to the README, and run it from the repo root so the paths work.

## Gotchas
- Looking at many factors and keeping the best one inflates the result. Count the rules you tried and say so; one "mildly interesting" rule out of ten is noise.
- Subgroups get small fast. Check that the effect holds with the next-largest threshold (job 21: wind 20+ had n=33 and showed nothing).
- Historical actuals (e.g. weather at kickoff) are cleaner than forecasts. Say which one you used.
- Market lines already contain most public factors. If the factor only matches the line, the honest answer is "no edge against the close".
- Stocks: the same test works with 20-day forward return vs a baseline of all days, see `stock-signal-model`.
- Not financial or betting advice; state the sample and the date of the data.
