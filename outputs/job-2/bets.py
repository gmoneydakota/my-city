#!/usr/bin/env python3
"""NFL + NBA betting model for DraftKings and Underdog.

    python3 bets.py nba                      # tonight's NBA card
    python3 bets.py nfl                      # this week's NFL card
    python3 bets.py all                      # both
    python3 bets.py nba --lines my_lines.csv # price lines you copied from Underdog / DK
    python3 bets.py backtest nba             # walk-forward test of the team model
    python3 bets.py grade                    # grade logged picks, show ROI

Optional: export ODDS_API_KEY=... (free at the-odds-api.com) for multi-book
consensus, DraftKings prop prices and Underdog lines pulled automatically.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from betmodel import engine, ratings, report  # noqa: E402
from betmodel.common import DataError, prune_cache  # noqa: E402


def card(league: str, a) -> None:
    key = os.environ.get("ODDS_API_KEY") or None
    print(f"[{league.upper()}] fetching slate, results, injuries"
          f"{' + Odds API' if key else ''} …", file=sys.stderr)
    res = engine.run(league, a.date, key, a.lines, not a.no_props, a.max_events, a.per_team, not a.no_sheet)
    picks = report.select(res, a.min_edge, a.min_edge_prop, a.bankroll)
    text = report.markdown(res, picks, a.bankroll, engine.ud_breakeven(3))
    path = report.write_outputs(res, picks, text)
    n = 0 if a.no_log else report.log_picks(res, picks, a.bankroll)
    print(text)
    print(f"\n[{league.upper()}] report saved to {path}" + (f"; {n} new picks logged for grading" if n else ""),
          file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["nba", "nfl", "all", "backtest", "grade"])
    ap.add_argument("league", nargs="?", choices=["nba", "nfl"], help="league for backtest")
    ap.add_argument("--date", help="YYYYMMDD slate (NBA: that day; NFL: that week). Default: today/this week")
    ap.add_argument("--lines", help="CSV of prop lines you copied (see README / sample_lines.csv)")
    ap.add_argument("--bankroll", type=float, default=500.0, help="bankroll in $ for stake sizing (default 500)")
    ap.add_argument("--min-edge", type=float, default=0.03, help="min EV per $1 for game bets (default 0.03)")
    ap.add_argument("--min-edge-prop", type=float, default=0.04, help="min EV per $1 for DK props (default 0.04)")
    ap.add_argument("--max-events", type=int, default=6, help="max games to pull Odds API props for (credits)")
    ap.add_argument("--per-team", type=int, default=5, help="players per team on the projection sheet")
    ap.add_argument("--no-props", action="store_true", help="game lines only (fast)")
    ap.add_argument("--no-sheet", action="store_true", help="skip the projection sheet")
    ap.add_argument("--no-log", action="store_true", help="don't append picks to history/picks.csv")
    a = ap.parse_args(argv)
    if a.lines and not os.path.exists(a.lines):
        ap.error(f"--lines file not found: {a.lines}")
    prune_cache()
    try:
        if a.command == "grade":
            print(report.grade())
        elif a.command == "backtest":
            if not a.league:
                ap.error("backtest needs a league: bets.py backtest nba")
            r = ratings.backtest(a.league)
            if "error" in r:
                print(r["error"])
                return 1
            print(f"{a.league.upper()} {r['season']} walk-forward: {r['games']} games, "
                  f"accuracy {r['accuracy']:.1%}, Brier {r['brier']:.4f}, margin MAE {r['margin_mae']:.2f} pts. "
                  f"({r['note']})")
        else:
            for lg in (["nba", "nfl"] if a.command == "all" else [a.command]):
                card(lg, a)
    except DataError as e:
        print(f"Data source error: {e}. Try again in a few minutes.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
