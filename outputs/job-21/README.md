# Job 21: Lucky Tower factor study (weather, defenses, rest, more)

Data as of **Sun 1 Nov 2026 (UTC)**. Weather: Open-Meteo forecast pulled 1 Nov. Prices/lines: `bets/reports/2026-11-01_*.md` (DraftKings via ESPN, pulled 22:22 UTC). Injuries: web search, no final inactives list was available.

## Short answer
**Weather, defense form and rest do not beat the closing line.** I tested them on 2,310 NFL games (2018-2025, walk-forward: fit on earlier seasons, bet the next one). The line already contains them. So the honest "best odds to win" is *not* a factor-built pick; it is "don't bet against the market unless you have news the market lacks".

## Backtest (`factor_backtest.py`, results in `backtest_results.json`)
Break-even at -110 is 52.4%.

| Model (predicts how far the game misses the line) | Bets | Win rate | Verdict |
|---|---|---|---|
| Totals: weather only (wind, cold, dome) | 943 | 51.1% | below break-even |
| Totals: both teams' scoring form | 275 | 50.9% | below break-even |
| Totals: weather + form + division + Thursday | 1128 | 52.1% | about break-even, loses to vig |
| Spreads: defense/offense gap + rest | 306 | 47.1% | loses |
| Spreads: all factors | 557 | 51.9% | below break-even |

Simple rules (share of games going UNDER; baseline all games 51.2%):
- Outdoor wind >= 15 mph: **57.2% under, n=159**, average 1.9 pts below the line. The only mildly interesting one, but ~1.8 standard errors, found after looking, and wind-20+ (n=33) shows nothing. Treat as a possible small lean, not proven.
- Cold <= 32F: 47.9% under (n=96). Dome: 48.8% under (n=691). Both near coin flips.
- Two strong defenses: 50.5% under. Two weak defenses: 54.3% under (n=833). Small, below useful.

Coefficients tell the same story: 10 mph more wind moves the total only ~1.7 points, and the market already prices most of that.

Existing evidence agrees: `bets/learned.json` shows the model's own strong leans at 40.9% hit rate (-7.5% ROI per bet) over 364 graded, and job 6 found no model beat NFL closing lines.

## Today's context (not a pick list)
| Game | Weather at kickoff | Defense form (last 8, pts allowed / league 23.0) | Notes |
|---|---|---|---|
| PHI @ WSH, Sun 8:20pm ET | ~53F falling to ~50F, wind 4-5 mph, 0% rain: **no weather effect** | PHI allows 25.0 (scores 18.1); WSH allows 28.7 (scores 22.0). Both below-average defenses | DK total 40.5 looks low vs two leaky defenses; the model's Over 40.5 (56%) fits that, but weak-defense games went under 46% of the time, so it is not a strong edge. Kinlaw (WSH DT) likely out; Barkley questionable pregame; Burks expected to play. Check inactives before kickoff. |
| CHI @ SEA, Mon 8:15pm ET | ~49-50F, wind 2-6 mph, ~1-4% rain: **no weather effect** | SEA allows 17.9 (strong); CHI allows 20.4, scores 25.7 | Model SEA -2.2 vs DK -3: basically agrees with the market, so no game bet. Bears RB Monangai out/doubtful per 29 Oct report; recheck Friday/Saturday reports. |

NBA (LAC @ GS, TOR @ LAL): the cached NBA data is season-long and not reliable for "last 8 games" form, so I did not score NBA defenses. GS is without Curry and Draymond per the card. The card shows only one NBA edge (Over 220.5, +3.3% EV). Treat that as thin.

## Best-odds ranking from the existing card, after this study
1. Highest-confidence *type* of bet: nothing. No factor gives a proven edge.
2. If you play anyway, the least-bad are: PHI @ WSH Over 40.5 (supported by two weak defenses and calm weather) and small anytime-TD/prop plays, but note props' blended hit rate has still lost money (see `learned.json`).
3. Avoid: PHI ML +220 and spread based on the model alone; the model sees PHI at pick'em while DK has WSH -6, and a gap that large usually means news you don't have. Job 6 found the model's disagreements on NFL sides were wrong more than right.
4. Underdog: no combination clears break-even today.

Stake nothing you can't lose; size small (the card uses 1/4 Kelly, 2% cap).

## Files
- `factor_backtest.py` - walk-forward test (needs `pip install pandas numpy`); run from repo root: `python3 outputs/job-21/factor_backtest.py`
- `current_factors.py` - scoring/form sheet for today's teams -> `current_factors.json`
- `backtest_results.json`, `current_factors.json` - outputs

## Assumptions / limits
- "Lucky Tower" = the `bets/` model. I did not edit it or the city (`index.html`); wiring factors into the tower would need an upgrade job, and this study says it wouldn't help.
- Historical weather = nflverse temp/wind at kickoff (actuals), not forecasts, so real forecasts are slightly noisier.
- Defense form = last-8 points allowed shrunk to the league average; no yards/EPA or opponent adjustment.
- Not tested: NBA (no cached market lines), referees, travel, coaching, player props with real lines.
- Games started 8:20pm ET Sunday, so by the time you read this the PHI/WSH game may be underway.

This is an educational model, not financial advice. Markets can move against any signal.
