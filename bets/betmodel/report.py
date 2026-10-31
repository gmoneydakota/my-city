"""Markdown/CSV/console output and the pick log used for grading."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import espn
from .common import ROOT, american_to_decimal, get_json, DataError

REPORTS = ROOT / "reports"
HISTORY = ROOT / "history" / "picks.csv"
PICK_FIELDS = ["logged_at", "league", "event_id", "start", "kind", "selection", "athlete_id", "stat", "side",
               "line", "price", "p", "ev", "stake_units", "book", "result", "profit_units"]
MAX_SANE_EV = 0.15  # bigger "edges" on main lines are almost always stale or bad data


def _odds(a) -> str:
    return "" if a is None else f"{int(a):+d}"


def _pct(x) -> str:
    return "" if x is None else f"{100 * x:.1f}%"


def _local(dt: datetime) -> str:
    # US Eastern without tz database: EST/EDT approximation (DST: 2nd Sun Mar – 1st Sun Nov)
    y = dt.year
    mar = datetime(y, 3, 8, 7, tzinfo=timezone.utc)
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc)
    start = mar + timedelta(days=(6 - mar.weekday()) % 7)
    end = nov + timedelta(days=(6 - nov.weekday()) % 7)
    off = -4 if start <= dt < end else -5
    return (dt + timedelta(hours=off)).strftime("%a %m/%d %I:%M%p ET")


def select(res: dict, min_edge_game: float, min_edge_prop: float, bankroll: float) -> dict:
    gb = [b for b in res["game_bets"] if b["ev"] >= min_edge_game and b["p"] >= 0.18]
    for b in gb:
        b["flag"] = "CHECK LINE (edge looks too big)" if b["ev"] > MAX_SANE_EV else ""
        b["stake"] = round(bankroll * b["kelly"], 2)
    gb.sort(key=lambda b: (bool(b["flag"]), -b["ev"]))  # suspicious edges go last
    pb = [b for b in res["prop_bets"] if b["ev"] >= min_edge_prop and b["p"] >= 0.25]
    for b in pb:
        b["stake"] = round(bankroll * b["kelly"], 2)
    pb.sort(key=lambda b: -b["ev"])
    legs = sorted((l for l in res["ud_legs"] if l["p"] > 0.5), key=lambda l: -l["value"])
    return {"game": gb, "prop": pb, "legs": legs}


def markdown(res: dict, picks: dict, bankroll: float, be3: float) -> str:
    L = res["league"].upper()
    m = res.get("model")
    out = [f"# {L} betting card — generated {res['generated']:%Y-%m-%d %H:%M} UTC", ""]
    out.append("Data: ESPN schedule/results/injuries/game logs + DraftKings lines as shown on ESPN, "
               f"pulled {res['generated']:%Y-%m-%d %H:%M} UTC. Lines move — re-check the price before betting.")
    if m:
        out.append(f"Team model fitted on {m.n_games} games; league avg {m.mu:.1f} pts/team, home edge "
                   f"{m.hca:+.1f}, margin σ {m.sigma_margin:.1f}, total σ {m.sigma_total:.1f}.")
    out.append(f"Stakes are ¼-Kelly on a ${bankroll:,.0f} bankroll, capped at 2% per bet.")
    out.append("")
    out.append(f"## 1. DraftKings game bets (ML / spread / total) — {len(picks['game'])} with an edge")
    if picks["game"]:
        out.append("| Game | Start | Bet | DK odds | Our prob | Market prob | EV/$1 | Stake | Model line | Notes |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for b in picks["game"]:
            out.append(f"| {b['game']} | {_local(b['start'])} | **{b['selection']}** | {_odds(b['price'])} | "
                       f"{_pct(b['p'])} | {_pct(b['p_market'])} ({b['n_books']} bk) | {b['ev']:+.3f} | "
                       f"${b['stake']:.2f} | {b['model_line']} | {b.get('flag', '')} {b['notes']} |")
    else:
        out.append("_No game line beats the DraftKings price by enough today. That's normal — passing is a bet too._")
    out.append("")
    out.append("### All games: model vs DraftKings")
    out.append("| Game | Start | DK spread | Model spread | DK total | Model total | Model home win% |")
    out.append("|---|---|---|---|---|---|---|")
    for g in res["games"]:
        p = g.get("pred")
        dk = g.get("dk") or {}
        if not p:
            continue
        sh = dk.get("spread_home")
        out.append(f"| {g['name']} | {_local(g['date'])} | {g['home_abbr']} {sh:+g} | "
                   f"{g['home_abbr']} {-p['margin']:+.1f} | {dk.get('total') or ''} | {p['total']:.1f} | "
                   f"{_pct(p['p_home'])} |" if sh is not None else
                   f"| {g['name']} | {_local(g['date'])} | – | {g['home_abbr']} {-p['margin']:+.1f} | – | "
                   f"{p['total']:.1f} | {_pct(p['p_home'])} |")
    out.append("")
    out.append(f"## 2. DraftKings player props — {len(picks['prop'])} with an edge")
    if picks["prop"]:
        out.append("| Player | Bet | DK odds | Proj | Our prob | Mkt prob(over) | EV/$1 | Stake | Last 5 | Notes |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for b in picks["prop"][:25]:
            out.append(f"| {b['player']} ({b['team']}) | **{b['side'].upper()} {b['line']:g} {b['stat']}** | "
                       f"{_odds(b['price'])} | {b['proj']:.1f} | {_pct(b['p'])} | {_pct(b['p_market_over'])} | "
                       f"{b['ev']:+.3f} | ${b['stake']:.2f} | {_last5(b['last5'])} | {b['notes']} |")
    elif res["prop_bets"]:
        out.append(f"_Priced {len(res['prop_bets'])} DraftKings prop sides; none clear the edge threshold "
                   "(full list in the _all_prices.csv)._")
    else:
        out.append("_Needs prop prices: set ODDS_API_KEY or pass --lines with DraftKings odds (see README)._")
    out.append("")
    out.append("## 3. Underdog pick'em")
    if picks["legs"]:
        out.append(f"Break-even per leg (standard): 2-pick {_pct(_be(2))}, 3-pick {_pct(_be(3))}, "
                   f"4-pick {_pct(_be(4))}, 5-pick {_pct(_be(5))}.")
        out.append("")
        if res["entries"]:
            out.append("### Suggested entries")
            for i, e in enumerate(res["entries"], 1):
                legs = "; ".join(f"{l['player']} {'Higher' if l['side'] == 'over' else 'Lower'} {l['line']:g} "
                                 f"{l['stat']} ({_pct(l['p'])})" for l in e["legs"])
                out.append(f"{i}. **{e['n']}-pick ({e['payout']:g}x)** — win prob {_pct(e['p_win'])}, "
                           f"EV {e['ev']:+.1%}: {legs}")
            out.append("")
            out.append("_Assumes legs are independent; max 2 legs per game to limit correlation._")
        else:
            out.append("_No combination of legs clears break-even today._")
        out.append("")
        out.append("### Best individual legs")
        out.append("| Player | Pick | Our prob | Proj | Mkt prob(over) | Last 5 | Notes |")
        out.append("|---|---|---|---|---|---|---|")
        for l in picks["legs"][:20]:
            mult = "" if l["mult"] == 1 else " ({:g}x)".format(l["mult"])
            out.append(f"| {l['player']} ({l['team']}) | {'Higher' if l['side'] == 'over' else 'Lower'} "
                       f"{l['line']:g} {l['stat']}{mult} | "
                       f"{_pct(l['p'])} | {l['proj']:.1f} | {_pct(l['p_market_over'])} | {_last5(l['last5'])} | "
                       f"{l['notes']} |")
    else:
        out.append("_No Underdog lines loaded. Use the projection sheet below against the Underdog app, or pass "
                   "--lines underdog.csv / set ODDS_API_KEY._")
    out.append("")
    if res["sheet"]:
        out.append("## 4. Projection sheet (compare to any app's line)")
        out.append(f"'Take Higher if line ≤' / 'Take Lower if line ≥' = where our probability reaches "
                   f"{_pct(be3)} (Underdog 3-pick break-even). Between the two, pass.")
        out.append("")
        out.append("| Game | Player | Stat | Proj | Fair line | Take Higher if line ≤ | Take Lower if line ≥ | Last 5 | Status |")
        out.append("|---|---|---|---|---|---|---|---|---|")
        for r in res["sheet"]:
            oa = "" if r["over_at"] is None else "{:g}".format(r["over_at"])
            ua = "" if r["under_at"] is None else "{:g}".format(r["under_at"])
            fair = r["fair"] if isinstance(r["fair"], str) else "{:g}".format(r["fair"])
            out.append(f"| {r['game']} | {r['player']} ({r['team']}) | {r['stat']} | {r['proj']:.2f} | {fair} | "
                       f"{oa} | {ua} | {_last5(r['last5'])} | {r['status']} |")
        out.append("")
    if res["warnings"]:
        out.append("## Warnings")
        out += [f"- {w}" for w in res["warnings"]]
        out.append("")
    out.append("---")
    out.append("Not financial advice. Even +EV bets lose often; size small and track results "
               "(`python3 bets.py grade`). Gambling problem? Call 1-800-GAMBLER.")
    return "\n".join(out)


def _be(n):
    from .engine import ud_breakeven
    return ud_breakeven(n)


def _last5(vals) -> str:
    return ",".join("-" if v is None else f"{v:g}" for v in vals)


def write_outputs(res, picks, text) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = f"{res['generated']:%Y-%m-%d}_{res['league']}"
    md = REPORTS / f"{stem}.md"
    md.write_text(text, encoding="utf-8")
    with open(REPORTS / f"{stem}_all_prices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "game", "selection", "line", "dk_odds", "p_model", "p_market", "p_blend", "ev"])
        for b in res["game_bets"]:
            w.writerow([b["kind"], b["game"], b["selection"], b["line"], b["price"], f"{b['p_model']:.4f}",
                        "" if b["p_market"] is None else f"{b['p_market']:.4f}", f"{b['p']:.4f}", f"{b['ev']:.4f}"])
        for b in res["prop_bets"]:
            w.writerow(["Prop", b["game"], b["selection"], b["line"], b["price"], "", "", f"{b['p']:.4f}",
                        f"{b['ev']:.4f}"])
    if res["sheet"]:
        with open(REPORTS / f"{stem}_projections.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["game", "team", "player", "stat", "proj", "sd", "fair_line", "higher_if_line_le",
                        "lower_if_line_ge", "status"])
            for r in res["sheet"]:
                w.writerow([r["game"], r["team"], r["player"], r["stat"], f"{r['proj']:.2f}", f"{r['sd']:.2f}",
                            r["fair"], r["over_at"], r["under_at"], r["status"]])
    return md


def log_picks(res, picks, bankroll):
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    new = not HISTORY.exists()
    existing = set()
    if not new:
        with open(HISTORY, newline="") as f:
            existing = {(r["event_id"], r["selection"]) for r in csv.DictReader(f)}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    with open(HISTORY, "a", newline="") as f:
        w = csv.DictWriter(f, PICK_FIELDS)
        if new:
            w.writeheader()
        for b in picks["game"] + picks["prop"]:
            if (b["event_id"], b["selection"]) in existing or b.get("flag"):
                continue
            w.writerow({"logged_at": now, "league": res["league"], "event_id": b["event_id"],
                        "start": b["start"].isoformat(), "kind": b["kind"], "selection": b["selection"],
                        "athlete_id": b.get("athlete_id", ""), "stat": b.get("stat", ""), "side": b.get("side", ""),
                        "line": "" if b.get("line") is None else b["line"], "price": b["price"],
                        "p": f"{b['p']:.4f}", "ev": f"{b['ev']:.4f}",
                        "stake_units": f"{100 * b['kelly']:.2f}", "book": "draftkings",
                        "result": "", "profit_units": ""})
            n += 1
    return n


# --------------------------------------------------------------------------- grading
def _final_score(league, event_id):
    try:
        d = get_json(f"{espn.SITE}/{espn._path(league)}/summary", {"event": event_id}, ttl_hours=2)
    except DataError:
        return None
    comp = d["header"]["competitions"][0]
    if not comp["status"]["type"].get("completed"):
        return None
    sc = {c["homeAway"]: (float(c["score"]), c["team"]["abbreviation"]) for c in comp["competitors"]}
    return sc


def grade() -> str:
    if not HISTORY.exists():
        return "No picks logged yet."
    with open(HISTORY, newline="") as f:
        rows = list(csv.DictReader(f))
    from .props import STATS
    for r in rows:
        if r["result"]:
            continue
        lg = r["league"]
        res = None
        if r["kind"] in ("ML", "Spread", "Total"):
            sc = _final_score(lg, r["event_id"])
            if not sc:
                continue
            (hs, ha), (as_, aa) = sc["home"], sc["away"]
            sel = r["selection"]
            if r["kind"] == "Total":
                tot, line = hs + as_, float(r["line"])
                diff = tot - line if sel.startswith("Over") else line - tot
            else:
                team = sel.split()[0]
                margin = hs - as_ if team == ha else as_ - hs
                diff = margin + (float(r["line"]) if r["kind"] == "Spread" else 0)
            res = "W" if diff > 0 else "L" if diff < 0 else "P"
        elif r["kind"] == "Prop":
            log = espn.gamelog(lg, r["athlete_id"])
            row = next((g for g in log if g["event_id"] == r["event_id"]), None)
            if row is None:
                if datetime.fromisoformat(r["start"]) < datetime.now(timezone.utc) - timedelta(days=2):
                    res = "VOID"  # player didn't play
                else:
                    continue
            else:
                v = STATS[lg][r["stat"]][0](row)
                if v is None:
                    continue
                diff = (v - float(r["line"])) * (1 if r["side"] == "over" else -1)
                res = "W" if diff > 0 else "L" if diff < 0 else "P"
        if res:
            stake = float(r["stake_units"] or 0)
            r["result"] = res
            r["profit_units"] = (f"{stake * (american_to_decimal(float(r['price'])) - 1):.2f}" if res == "W"
                                 else f"{-stake:.2f}" if res == "L" else "0.00")
    with open(HISTORY, "w", newline="") as f:
        w = csv.DictWriter(f, PICK_FIELDS)
        w.writeheader()
        w.writerows(rows)
    done = [r for r in rows if r["result"] in ("W", "L", "P")]
    if not done:
        return f"{len(rows)} picks logged, none graded yet (games not final)."
    staked = sum(float(r["stake_units"] or 0) for r in done if r["result"] != "P")
    profit = sum(float(r["profit_units"] or 0) for r in done)
    w_ = sum(r["result"] == "W" for r in done)
    l_ = sum(r["result"] == "L" for r in done)
    exp = sum(float(r["ev"]) * float(r["stake_units"] or 0) for r in done)
    return (f"Graded {len(done)} picks: {w_}-{l_}-{len(done) - w_ - l_} (W-L-P). "
            f"Staked {staked:.1f}u (1u = 1% bankroll), profit {profit:+.2f}u, ROI "
            f"{(profit / staked if staked else 0):+.1%}. Model expected {exp:+.2f}u. "
            f"Needs a few hundred bets before ROI means much.")
