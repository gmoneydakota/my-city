# Job 22: weekly betting-model self-improvement (2026-11-02)

## What the data says (graded rows in shadow_bets.csv; only 2 days of history: 31 Oct and 1 Nov)
- Model leans: 199W-258L (43.5%), ROI -5.2% per bet. Strong leans: 40.9%, ROI -7.5%.
- Most of the damage is on 1 Nov (NFL props: 242 positive-EV bets, 35.5% win, ROI -11%).
  31 Oct props were fine (71 bets, 56% win, ROI +6%).
- **Weakness 1 (fixed): NFL `anytime_td` has no market anchor.** DraftKings posts only the "yes" price,
  so no vig-free market probability existed and `p` was the model alone (the learned prop weight of 0.236 never applied).
  161 graded bets: 13.8% win vs model 20.7%, ROI -15%. By the market's implied probability:

  | market implied | n | model p | actual win |
  |---|---|---|---|
  | under 10% (long shots) | 55 | 12.2% | **5.5%** |
  | 10-20% | 28 | 15.9% | 14.3% |
  | 20-30% | 38 | 24.8% | 21.1% |

  The model floored every long shot at about 10% (+2500 to +5500 priced at 10.1%, "EV" +160% to +415%), and all of them lost.
  The market price itself was roughly right at the low end (implied about 4-6% vs 5.5% actual).
- Seen but NOT changed (too thin): the NFL yardage/receptions scales are already being adjusted by the learner.
  NBA overs lose while unders win, but that is 2 days of data and the learner already cut NBA projections about 5%.
  ML, Spread and Total have fewer than 50 graded rows each.

## Change
- `bets/betmodel/engine.py`: new `one_sided_fair()` and `ONE_SIDED_STATS`. With no two-way market for `anytime_td`,
  the fair probability is the "yes" price with a 10% hold removed (implied x 0.90), from non-DFS books that post no under.
  `prop_bets` blends it with the model using the learned `prop_weight`, like every other prop.
  Example: a +3000 long shot goes from 10.1% (model only) to about 5.6% blended, so the fake +200% edge disappears.
- `bets/test_betmodel.py`: 3 new tests (`OneSidedMarket`). `cd bets && python3 test_betmodel.py` gives 15 tests, all OK.

## What you will see after approving
Anytime-TD long shots stop showing up as huge-EV picks; mid-priced anytime-TD bets move slightly toward the market. Nothing else changes.
Next week, check anytime_td ROI and the under-10% bucket in shadow_bets.csv.

## Assumptions
- The 10% hold is a typical figure, not measured; refine it when there is more data.
- The 0.236 prop weight was learned from two-way props and is reused here.
- `history/` and `learned.json` were not touched.
