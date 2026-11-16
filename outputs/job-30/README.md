# Job 30: weekly betting-model self-improvement (16 Nov 2026)

## What I found (graded rows in `bets/history/shadow_bets.csv`, 31 Oct to 15 Nov)
- Main lines (ML/Spread/Total) are exactly 50% by construction (both sides logged); nothing to learn from win rate. ROI is about -4.5% (the vig).
- **Prop side bias (the one real weakness):** across about 4,380 over/under pairs (excluding anytime TD), overs won about 45% where prices implied about 53%; unders won about 55%. The market's own de-vigged P(over) averages 0.495, so blending with the market does not remove it. Over ROI: NBA points -14.5%, NFL rec_yds -13.7%, receptions -18%, rush_yds -12.5%.
  - NFL held in both halves: 44.0% early (n=505), 45.8% late (n=590), vs about 52-53% implied.
  - NBA was 39.2% early (n=590) but 50.1% late (n=369) vs 53% implied: it may be fading.
- The job 27 side-bias finding is in the brain, but no such constant existed in `bets/betmodel/`; the fix was never in the code.
- Not changed (too thin or fine): anytime TD (292 rows, won 17.8% vs implied 19.2%, model p 20.9%; one-sided hold fix is in place, rows partly pre-fix); NFL pass_yds and NBA assists/rebounds/PRA (under 100 rows each); learned weights and calibration (daily learner owns them).

## What changed
- `bets/betmodel/engine.py`: new `OVER_SHIFT = {"nfl": 0.02, "nba": 0.01}` and `side_adjust()`, applied to P(over) of two-way props right after the model/market blend. P(under) rises by the same amount. Anytime TD (one-sided) is untouched.
- `bets/test_betmodel.py`: 3 new tests (`SideBias`). `cd bets && python3 test_betmodel.py` passes.
- `brain/skills/betting-model-learning.md`: two gotchas added.

## Judgement calls
- The shift is roughly half the observed gap (a judgement, not a fit); NBA is smaller because the late window showed no gap.
- Effect: fewer over recommendations; some marginal unders now qualify. Unders were only +3% ROI on points/rec_yds and the sample is two weeks, so the edge is small.
- **Re-check on 2026-12-01:** raise if overs still trail implied by more than 4 points; set to 0 if the gap has closed.

Assumptions: pushes are excluded from W/L; shadow rows reflect the model at logging time.

After approval, the daily board will lean slightly less toward overs and more toward unders on two-way props.

This is an educational model, not financial advice. Markets can move against any signal.
