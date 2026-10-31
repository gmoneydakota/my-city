# NFL + NBA betting model (DraftKings + Underdog)

A command-line model that builds a daily **betting card** for NBA and NFL:

1. **DraftKings game bets:** moneylines, spreads and totals where our probability beats the DK price.
2. **DraftKings player props:** points, rebounds, assists, threes, PRA, pass/rush/receiving yards, receptions, anytime TD.
3. **Underdog pick'em:** each leg's win probability compared with Underdog's break-even, plus the best 2–5-pick entries.
4. **Projection sheet:** a projection and a "take Higher if the line is ≤ X / take Lower if ≥ Y" range for the main players in every game. You can hold it up against the Underdog or DK app even when you haven't loaded any lines.

It runs on Python 3.9+ with **no packages to install**. Data comes from free ESPN endpoints. An
[Odds API](https://the-odds-api.com) key is optional and adds a lot (see below).

Example cards from this run (data pulled **31 Oct 2026, ~16:40 UTC**) are in `reports/`.

---

## Quick start

```bash
cd outputs/job-2
python3 bets.py nba            # tonight's NBA card
python3 bets.py nfl            # this week's NFL card
python3 bets.py all            # both
```

Each run prints the card and saves:

| File | What's in it |
|---|---|
| `reports/<date>_<league>.md` | The card (open it in any Markdown viewer or on GitHub) |
| `reports/<date>_<league>_all_prices.csv` | Every bet that was priced, including the ones that didn't qualify |
| `reports/<date>_<league>_projections.csv` | Projection sheet in spreadsheet form |
| `history/picks.csv` | Every recommended DK bet, so it can be graded later |

The first run of the day takes about 1–3 minutes because it downloads game logs. Runs after that use the cache in `.cache/` (pruned after 3 days).

### Options

```
--date YYYYMMDD     slate for another day (NBA: that day; NFL: that date's games)
--bankroll 500      bankroll used for stake sizing (1/4 Kelly, max 2% per bet)
--min-edge 0.03     minimum expected profit per $1 for game bets
--min-edge-prop 0.04  same for DK props
--lines FILE.csv    price lines you copied from Underdog/DK (below)
--per-team 5        players per team on the projection sheet
--max-events 6      Odds API: how many games to pull props for (each costs credits)
--no-props          game lines only (fast)
--no-sheet          skip the projection sheet
--no-log            don't add picks to history/picks.csv
```

### Grade your results

```bash
python3 bets.py grade
```

This grades logged picks once the games are final (scores from ESPN, props from box scores) and prints W-L, units, ROI and what the model *expected* to win. You need a few hundred bets before the ROI tells you much.

### Check the model

```bash
python3 bets.py backtest nba
python3 bets.py backtest nfl
python3 test_betmodel.py        # offline unit tests
```

Walk-forward results on the last full season (refit every 14 days, each game predicted only from earlier games):

| League | Games | Winner picked | Brier score | Margin error |
|---|---|---|---|---|
| NBA 2025-26 | 1,075 | 67.9% | 0.2075 | 11.6 pts |
| NFL 2025 | 222 | 59.5% | 0.2305 | 10.5 pts |

A Brier score of 0.25 is a coin flip, and lower is better. These scores are solid for a public-data model but not as good as the closing betting line. **That is why the model never bets its own opinion alone: it blends with the market.**

---

## Getting Underdog and DraftKings prop lines in

ESPN shows DraftKings **game** lines for free, but not props, and Underdog has no public API. There are two ways to load prop lines:

### Option A: Odds API key (automatic, recommended)
1. Get a free key at https://the-odds-api.com (500 credits/month).
2. `export ODDS_API_KEY=your_key` (Windows PowerShell: `$env:ODDS_API_KEY="your_key"`).
3. Run `python3 bets.py nba` as usual.

With a key the model gets:
- a **multi-book consensus** (FanDuel, BetMGM, Caesars, Pinnacle…), which is a much sharper "fair price" than DK alone,
- **DraftKings prop prices** for the "DK props" section,
- **Underdog pick'em lines** for the Underdog section.

Cost: about 3 credits per run for game lines, plus about 5 credits per game for props. Use `--max-events` to stay inside the free tier. For example, `--max-events 3` uses roughly 18 credits per run.

### Option B: paste lines into a CSV (free)
Copy lines from the apps into a CSV like `sample_lines.csv`:

```csv
league,player,stat,line,book,over_odds,under_odds,mult_over,mult_under
nba,Tyrese Maxey,points,26.5,underdog,,,,
nba,Brandon Miller,threes,2.5,underdog,,,1.05,0.9
nba,Jrue Holiday,assists,4.5,draftkings,-130,+100,,
nfl,Ja'Marr Chase,receiving yards,80.5,underdog,,,,
```

- `book` is `underdog` or `draftkings`.
- `over_odds` and `under_odds` are the DK American odds. Leave them blank for Underdog.
- `mult_over` and `mult_under` are optional per-pick Underdog multipliers (e.g. 1.05x). Leave them blank for standard picks.
- `stat` can be `points, rebounds, assists, threes, pra, pr, pa, ra, blocks, steals, turnovers, blk_stl, pass_yds, pass_tds, pass_att, completions, interceptions, rush_yds, rush_att, receptions, rec_yds, rush_rec_yds, anytime_td`. Underdog-style names like "Pts+Rebs+Asts" and "Receiving Yards" also work.

Then run `python3 bets.py nba --lines my_lines.csv`. Note that `sample_lines.csv` contains **made-up lines** and is only there to show the format.

---

## How the model works

**Team model (moneylines, spreads, totals).** Each team gets an opponent-adjusted offense and defense rating, fit on every game from this season and last season. Recent games count more, and last season counts at about half weight. From those ratings it predicts both teams' scores, which gives a margin and a total. On top of that:
- **Home edge** is estimated from the data.
- **NBA back-to-backs** cost 1.5 points.
- **Injuries** come from ESPN's report. In the NBA, each missing player costs his team points based on his Game Score above replacement level. The cost is scaled by how much he had actually been playing, so long-term absences are already in the ratings, and day-to-day players count about 30%. In the NFL, only a missing starting QB is priced, at about 5 points.
- **Win, cover and over probabilities** come from a normal distribution, using the model's own error size measured on past games.

**Player props.** Each projection starts from a recency-weighted average of the player's game log, with last season at reduced weight:
- **NBA:** per-minute production × expected minutes from the last few games, so role changes show up quickly.
- **Game environment:** the projection is scaled by the team total implied by DraftKings' spread and total, compared with the team's normal scoring. A shootout means more points; a slog means fewer.
- **Distribution:** the player's own spread of outcomes. Low counts (threes, receptions, TDs, rebounds) use a negative binomial; points and yards use a normal. Pushes on whole-number lines are handled.
- **Shrinkage:** model probabilities are pulled 20% toward 50/50, because projection models are overconfident.
- Players listed Out or Doubtful are skipped. Questionable and day-to-day players are flagged.

**Blending with the market (the important part).**
`final prob = w × model + (1 − w) × de-vigged market`, where w = 0.30 for game lines and 0.50 for props, since prop markets are softer. Vig is removed with the power method. The market is the median across books when you have an Odds API key, and DraftKings alone otherwise. A bet is shown only if this blended probability still beats the price:
- **DraftKings:** expected value = p × decimal odds − 1 must be at least `--min-edge`. Edges above 15% on main lines are labeled **CHECK LINE**. They usually mean stale odds or news the model hasn't seen, and they are never logged.
- **Underdog:** standard pick'em pays 3x / 6x / 10x / 20x for 2 / 3 / 4 / 5 picks, so the break-even per leg is **57.7% / 55.0% / 56.2% / 54.9%**. The entry builder only uses legs above break-even, allows at most 2 legs from the same game (to limit correlation), and ranks entries by EV.

**Stakes** are ¼-Kelly, capped at 2% of bankroll per bet.

---

## How to use it well

- **Your best edges are usually Underdog legs and DK props**, not sides and totals. Prop lines are softer, and the model's prop logic is its strongest part.
- **Run it close to game time.** Injury news is the biggest mover. NBA: run it about 30–60 minutes before tip. NFL: run it Sunday morning after inactives.
- **When the model and DK disagree by a lot on a spread (5+ points), assume the market knows something first.** Examples are a QB change or a star resting. On 31 Oct, PHI @ WSH (DK WSH −6, model pick'em) and MIN @ SA were both like this. Check the news before betting.
- **Shop lines.** If another app has a better price, the EV is higher than shown.
- **Track everything** with `bets.py grade`. Lower your stakes if results run well below "model expected".

## Limitations (please read)

- This is a probabilistic model, not a guarantee. Even +EV bets lose often. No public model reliably beats closing lines on NFL/NBA sides.
- **Early-season** NBA ratings lean on last season's data. Rosters change, so trust game-line picks less until about 15 games in.
- The model does not project usage boosts when a teammate is out, or NFL injuries other than the QB. It also ignores weather, coaching changes and same-game correlation beyond the "2 per game" cap.
- DraftKings odds come from ESPN's feed, which can lag DK by minutes. **Always confirm the price in the app.**
- Underdog payouts and promotions change. If yours differ, edit `UD_PAYOUTS` in `betmodel/engine.py`.
- The Odds API integration (market names, the `underdog` bookmaker key) follows The Odds API v4 conventions but **was not tested live**, because no key was available. If a call fails, the card still runs on ESPN data and shows a warning.
- Only bet where it's legal for you and you're of age. Gambling problem? **1-800-GAMBLER**.

## Files

```
bets.py               command line: nba | nfl | all | backtest <lg> | grade
betmodel/espn.py      ESPN data: slate + DK lines, results, injuries, rosters, game logs
betmodel/ratings.py   team offense/defense model + walk-forward backtest
betmodel/injuries.py  injury report -> point adjustments
betmodel/props.py     player projections and distributions
betmodel/oddsapi.py   optional Odds API: consensus lines, DK props, Underdog lines
betmodel/engine.py    blending, EV, Underdog entries, projection sheet
betmodel/report.py    Markdown/CSV output, pick log, grading
betmodel/common.py    HTTP cache, odds math, distributions
test_betmodel.py      offline unit tests
sample_lines.csv      example --lines file (fake lines)
reports/              cards generated 31 Oct 2026
history/picks.csv     picks logged from the 31 Oct run (for `grade`)
```
