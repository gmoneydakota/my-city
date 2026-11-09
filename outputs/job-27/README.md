# Job #27

The change is made and tests pass (`cd bets && python3 test_betmodel.py`: 22 tests, OK). The README, `PROGRESS.md` and the brain-skill update were written, but the last command only returned an approval prompt for its `git status`, so I haven't confirmed those files landed.

**The weakness:** player-prop overs lose and unders win. On two-way props (NFL anytime TD excluded) I counted 1,237 over/under pairs. Overs won 43.2% where the price implied 49.3%, a gap of about 4 standard errors. Overs lost 17.6% per bet and unders made 6.3%. It shows in both NBA and NFL, in both halves of the window, and in each market-probability bucket. The market's own de-vigged probability was about 49.4%, so blending with it doesn't remove the bias.

**The change:**
- **`bets/betmodel/engine.py`:** a new `OVER_BIAS = 0.03` and `over_bias_adjust()` lower P(over) by 3 points after the model/market blend. That is half the observed gap, because the data covers only nine days. Anytime TD is skipped. Underdog legs move too.
- **`bets/test_betmodel.py`:** `OverBiasTest` has two tests, over/under symmetry, and the anytime-TD skip plus probability bounds.

**Left alone:**
- **NFL anytime TD:** job 22's one-sided fix already works. The 96 priced-with-market rows are calibrated (32.4% modelled vs 34.4% won).
- **NBA totals and spreads at EV 5% or more:** 35 and 9 bets.
- **Moneylines:** the sample is too thin to justify a change.

**Assumptions:**
- The 3-point shift is my judgement, not a fit, and I don't know the cause.
- I suggest re-checking around 2026-11-23: raise the shift toward 0.05 if overs still win under 47%, or set it to 0 if they reach about 49%.

I also added a step to `brain/skills/betting-model-learning.md` on splitting props by over/under side.

This is an educational model, not financial advice. Markets can move against any signal.
