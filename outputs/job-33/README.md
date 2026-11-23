# Job 33 – weekly betting-model self-improvement (data as of 2026-11-23, graded 2026-10-31..11-22)

## What I saw (8,386 graded bets, 11,834 graded projections)
- Model leans: 415 W / 524 L (44.2%, ROI -5.2%); strong leans 249/402 (38.3%, ROI -13.8%). Still worse than the market.
- Game markets (ML/Spread/Total): the learner already trusts the model only 4-8%; log-loss model 0.60-0.73 vs market 0.54-0.69. Nothing to add.
- **Weakness 1: the OVER side of two-way props.** Non-anytime-TD overs won **45.3%** where the de-vigged market said **49.5%** (n=2,887, SE 0.9 pts, about 4.5 SE). Unders won ~54-55% (ROI +2-3%); overs lost 14-15%. Holds in NBA and NFL. Weekly gap: 8.2, 3.5, 3.5, 1.5 pts. It is shrinking, so the early weeks inflate the average.
- Long shots (<30% implied) still lose 28-40% ROI in shadow bets, but the job-22 anytime-TD fix only applies to recent rows; too few to judge. No change.
- Calibration scales are all within 0.975-1.025, so projection means are fine. The learner already handles the NFL sd scales (~1.24).

## Change (one)
`bets/betmodel/engine.py`: `OVER_BIAS = 0.02` and `side_bias_adjust()`. P(over) is lowered by 2 pts on two-way props after the model/market blend (so the under gains 2 pts). One-sided markets (`anytime_td`) are exempt. 2 pts is about half the average gap and about the recent-weeks gap: a judgement, not a fit. The market probability itself carries the bias, so blending alone cannot fix it.
(Job 27's README described a side-bias fix, but no such constant existed in the code; this job adds it.)

**Re-check ~2026-12-14:** raise if the late gap stays above 3 pts; set to 0 if below 1 pt.

Test: `test_over_bias_two_way_only` in `bets/test_betmodel.py`. `cd bets && python3 test_betmodel.py` gives 21 tests OK.

## Not changed / assumptions
- `bets/history/` and `learned.json` untouched.
- The logged `p_market` is unadjusted, so next week's comparison can use it as the baseline.
- After approval, the board will show fewer over-side value flags and slightly more under-side ones.
