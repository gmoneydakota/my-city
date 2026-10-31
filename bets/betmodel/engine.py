"""Turns data + models into ranked bets.

Philosophy: betting markets are sharp. A model alone that disagrees with the
market is usually wrong, so every probability here is a *blend* of the model and
the de-vigged market (multi-book consensus when an Odds API key is provided,
DraftKings alone otherwise). A bet is only shown when that blended probability
still beats the price you'd actually get (DraftKings odds, or Underdog's
pick'em break-even).
"""
from __future__ import annotations

import csv
import itertools
import statistics
from datetime import datetime, timedelta, timezone

from . import espn, injuries, oddsapi, props, ratings
from . import learn
from .common import american_to_decimal, devig_two_way, expected_value, kelly_fraction, prob_to_american

W_MODEL_GAME = 0.30   # weight on our team model vs market for ML/spread/total
W_MODEL_PROP = 0.50   # props are softer markets, so the model gets more say
UD_PAYOUTS = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0}  # Underdog standard pick'em (all correct)
OUT_STATUSES = {"out", "doubtful", "injured reserve", "suspension", "ir"}


def ud_breakeven(n: int, payouts=UD_PAYOUTS) -> float:
    return (1 / payouts[n]) ** (1 / n)


# --------------------------------------------------------------------------- market helpers
def _fair_from_books(books: list[dict], a_key: str, b_key: str, line_key: str | None = None,
                     line=None) -> tuple[float | None, int]:
    """Median de-vigged prob of side A across books quoting both sides (at the same line)."""
    ps = []
    for b in books:
        oa, ob = b.get(a_key), b.get(b_key)
        if oa is None or ob is None:
            continue
        if line_key and (b.get(line_key) is None or line is None or abs(b[line_key] - line) > 1e-9):
            continue
        try:
            ps.append(devig_two_way(oa, ob)[0])
        except (ValueError, ZeroDivisionError):
            continue
    return (statistics.median(ps), len(ps)) if ps else (None, 0)


def _bet(kind, game, selection, line, price, p_model, p_market, n_books, w, notes="", **extra):
    w = learn.game_weight(kind, w)
    p = p_model if p_market is None else w * p_model + (1 - w) * p_market
    return dict(kind=kind, game=game["name"], event_id=game["event_id"], start=game["date"],
                selection=selection, line=line, price=price, p_model=p_model, p_market=p_market,
                n_books=n_books, p=p, ev=expected_value(p, price), kelly=kelly_fraction(p, price),
                notes=notes, **extra)


# --------------------------------------------------------------------------- game bets
def game_bets(league: str, games: list[dict], model: ratings.TeamModel, consensus: dict,
              inj_adj: dict, inj_desc: dict) -> list[dict]:
    tm = espn.teams(league)
    out = []
    for g in games:
        pred = model.predict(g["home"], g["away"], g["date"], g["neutral"],
                             inj_adj.get(g["home"], 0.0), inj_adj.get(g["away"], 0.0))
        g["pred"] = pred
        g["inj_desc"] = {t: inj_desc.get(t, []) for t in (g["home"], g["away"])}
        dk = g.get("dk")
        if not dk:
            continue
        hn = oddsapi.nickname(tm.get(g["home"], {}).get("name", ""))
        an = oddsapi.nickname(tm.get(g["away"], {}).get("name", ""))
        books = list((consensus.get((hn, an)) or {}).get("books", {}).values())
        if not books:
            books = [dk]
        notes = []
        if pred["home_b2b"]:
            notes.append(f"{g['home_abbr']} on back-to-back")
        if pred["away_b2b"]:
            notes.append(f"{g['away_abbr']} on back-to-back")
        priced = ([f"{g['home_abbr']} {d}" for d in g["inj_desc"][g["home"]]]
                  + [f"{g['away_abbr']} {d}" for d in g["inj_desc"][g["away"]]])
        if priced:
            notes.append("Injuries priced: " + ", ".join(priced[:6]) + (" …" if len(priced) > 6 else ""))
        note = "; ".join(notes)
        ctx = dict(model_line=f"{g['home_abbr']} {-pred['margin']:+.1f}, total {pred['total']:.1f}")

        # moneyline
        if dk["ml_home"] and dk["ml_away"]:
            pm, n = _fair_from_books(books, "ml_home", "ml_away")
            out.append(_bet("ML", g, f"{g['home_abbr']} ML", None, dk["ml_home"], pred["p_home"], pm, n,
                            W_MODEL_GAME, note, **ctx))
            out.append(_bet("ML", g, f"{g['away_abbr']} ML", None, dk["ml_away"], 1 - pred["p_home"],
                            None if pm is None else 1 - pm, n, W_MODEL_GAME, note, **ctx))
        # spread
        sh = dk["spread_home"]
        if sh is not None and dk["spread_home_odds"] and dk["spread_away_odds"]:
            pm, n = _fair_from_books(books, "spread_home_odds", "spread_away_odds", "spread_home", sh)
            pc = model.p_home_cover(pred["margin"], sh)
            out.append(_bet("Spread", g, f"{g['home_abbr']} {sh:+g}", sh, dk["spread_home_odds"], pc, pm, n,
                            W_MODEL_GAME, note, **ctx))
            out.append(_bet("Spread", g, f"{g['away_abbr']} {-sh:+g}", -sh, dk["spread_away_odds"], 1 - pc,
                            None if pm is None else 1 - pm, n, W_MODEL_GAME, note, **ctx))
        # total
        t = dk["total"]
        if t is not None and dk["over_odds"] and dk["under_odds"]:
            pm, n = _fair_from_books(books, "over_odds", "under_odds", "total", t)
            po = model.p_over(pred["total"], t)
            out.append(_bet("Total", g, f"Over {t:g}", t, dk["over_odds"], po, pm, n, W_MODEL_GAME, note, **ctx))
            out.append(_bet("Total", g, f"Under {t:g}", t, dk["under_odds"], 1 - po,
                            None if pm is None else 1 - pm, n, W_MODEL_GAME, note, **ctx))
    return out


# --------------------------------------------------------------------------- props
def env_factor(model: ratings.TeamModel, game: dict, team_id: str) -> float:
    """Implied team total (from DK spread+total, else our model) / team's normal output."""
    base = model.team_baseline(team_id)
    if base <= 0:
        return 1.0
    dk = game.get("dk") or {}
    is_home = team_id == game["home"]
    if dk.get("total") and dk.get("spread_home") is not None:
        spread_t = dk["spread_home"] if is_home else -dk["spread_home"]
        implied = dk["total"] / 2 - spread_t / 2
    else:
        pred = game.get("pred") or model.predict(game["home"], game["away"], game["date"], game["neutral"])
        implied = pred["home_pts"] if is_home else pred["away_pts"]
    return min(1.18, max(0.85, implied / base))


def load_lines_csv(path: str, league: str) -> list[dict]:
    """Manual lines (e.g. copied from the Underdog or DraftKings app).

    Columns: player,stat,line,book[,over_odds,under_odds,mult_over,mult_under,league]
    """
    quotes = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            if r.get("league") and r["league"].lower() != league:
                continue
            stat = props.canon_stat(league, r.get("stat", ""))
            try:
                line = float(r.get("line", ""))
            except ValueError:
                print(f"  [lines csv] row {i}: bad line {r.get('line')!r}, skipped")
                continue
            if not stat or not r.get("player"):
                print(f"  [lines csv] row {i}: unknown stat {r.get('stat')!r} or no player, skipped")
                continue
            book = (r.get("book") or "underdog").lower().replace(" ", "")
            for side in ("over", "under"):
                price = r.get(f"{side}_odds") or None
                mult = r.get(f"mult_{side}") or None
                quotes.append({"player": r["player"], "stat": stat, "line": line, "side": side,
                               "price": float(price) if price else None, "book": book,
                               "mult": float(mult) if mult else 1.0})
    return quotes


def prop_bets(league: str, games: list[dict], model, pbook: props.PlayerBook, quotes: list[dict],
              inj: dict) -> tuple[list[dict], list[dict], list[str]]:
    """Returns (DraftKings prop bets, Underdog legs, warnings)."""
    team_game = {}
    for g in games:
        team_game[g["home"]] = g
        team_game[g["away"]] = g
    groups: dict[tuple, dict] = {}
    for q in quotes:
        k = (espn.norm_name(q["player"]), q["stat"], q["line"])
        grp = groups.setdefault(k, {"player": q["player"], "books": {}})
        grp["books"].setdefault(q["book"], {})[q["side"]] = q
    warnings, dk_bets, ud_legs = [], [], []
    ids = []
    for (_, stat, line), grp in groups.items():
        p = pbook.find(grp["player"])
        grp["p"] = p
        if p:
            ids.append(p["id"])
    pbook.prefetch(ids)
    for (nname, stat, line), grp in groups.items():
        p = grp["p"]
        if not p or p["team_id"] not in team_game:
            warnings.append(f"no match on this slate for {grp['player']} ({stat})")
            continue
        g = team_game[p["team_id"]]
        injury = inj.get(nname)
        if injury and injury["status"].lower() in OUT_STATUSES:
            continue
        proj = learn.adjust(league, stat, props.project(league, pbook.log(p["id"]), stat, env_factor(model, g, p["team_id"])))
        if not proj:
            warnings.append(f"not enough games for {grp['player']} {stat}")
            continue
        mo, mu_, push = props.model_probs(proj, line)
        # consensus from sportsbooks with both sides at this line
        fair = []
        for bk, sides in grp["books"].items():
            if bk in oddsapi.DFS_BOOKS:
                continue
            o, u = sides.get("over", {}).get("price"), sides.get("under", {}).get("price")
            if o and u:
                try:
                    fair.append(devig_two_way(o, u)[0])
                except (ValueError, ZeroDivisionError):
                    pass
        p_mkt = statistics.median(fair) if fair else None
        played = mo + mu_
        p_over_model = mo / played if played else 0.5
        w_prop = learn.prop_weight(W_MODEL_PROP)
        p_over = p_over_model if p_mkt is None else w_prop * p_over_model + (1 - w_prop) * p_mkt
        note = f"{injury['status']}: {injury['detail']}" if injury else ""
        base = dict(player=p["name"], team=g["home_abbr"] if p["team_id"] == g["home"] else g["away_abbr"],
                    game=g["name"], event_id=g["event_id"], athlete_id=p["id"], stat=stat, line=line,
                    proj=proj["mean"], sd=proj["sd"], last5=proj["last5"], p_market_over=p_mkt,
                    n_books=len(fair), notes=note, start=g["date"])
        for bk, sides in grp["books"].items():
            for side in ("over", "under"):
                q = sides.get(side)
                if not q:
                    continue
                p_side = p_over if side == "over" else 1 - p_over
                if bk in oddsapi.DFS_BOOKS:
                    ud_legs.append(dict(base, side=side, p=p_side, mult=q.get("mult", 1.0),
                                        value=p_side * q.get("mult", 1.0)))
                elif bk == "draftkings" and q.get("price"):
                    pw = p_side * (1 - push)  # pushes refund the stake
                    pl = (1 - p_side) * (1 - push)
                    ev = pw * (american_to_decimal(q["price"]) - 1) - pl
                    dk_bets.append(dict(base, kind="Prop", side=side, selection=f"{p['name']} {side} {line:g} {stat}",
                                        price=q["price"], p=p_side, ev=ev,
                                        p_model=p_over_model if side == "over" else 1 - p_over_model,
                                        p_market=None if p_mkt is None else (p_mkt if side == "over" else 1 - p_mkt),
                                        kelly=kelly_fraction(p_side, q["price"]) * (1 - push)))
    return dk_bets, ud_legs, warnings


def best_entries(legs: list[dict], payouts=UD_PAYOUTS, top: int = 3, max_per_game: int = 2) -> list[dict]:
    """Best Underdog pick'em entries from the legs. Assumes independence between legs
    (we cap legs per game to limit correlation) — real results vary."""
    # one leg per player+stat, keep the better side
    best = {}
    for l in legs:
        k = (l["athlete_id"], l["stat"])
        if k not in best or l["value"] > best[k]["value"]:
            best[k] = l
    pool = sorted(best.values(), key=lambda l: -l["value"])[:14]
    entries = []
    for n in sorted(payouts):
        be = ud_breakeven(n, payouts)
        cand = [l for l in pool if l["value"] >= be]
        for combo in itertools.combinations(cand, n):
            games = [c["event_id"] for c in combo]
            players = [c["athlete_id"] for c in combo]
            if len(set(players)) < n or max(games.count(x) for x in games) > max_per_game:
                continue
            p_all = 1.0
            for c in combo:
                p_all *= c["value"]
            entries.append({"n": n, "legs": combo, "p_win": p_all, "ev": p_all * payouts[n] - 1,
                            "payout": payouts[n]})
    entries.sort(key=lambda e: -e["ev"])
    # don't show near-duplicate entries: require at least one new leg vs previously shown
    shown, used = [], []
    for e in entries:
        key = {(l["athlete_id"], l["stat"]) for l in e["legs"]}
        if any(key <= u for u in used):
            continue
        shown.append(e)
        used.append(key)
        if len(shown) >= top:
            break
    return shown


def projection_sheet(league: str, games: list[dict], model, pbook: props.PlayerBook, inj: dict,
                     per_team: int, target: float) -> list[dict]:
    """No-key mode: projections + 'bet it if the line is at/below X' thresholds."""
    rows = []
    for g in games:
        for tid in (g["home"], g["away"]):
            players = props.key_players(league, pbook, tid, per_team)
            pbook.prefetch([p["id"] for p in players])
            ef = env_factor(model, g, tid)
            for p in players:
                injury = inj.get(espn.norm_name(p["name"]))
                if injury and injury["status"].lower() in OUT_STATUSES:
                    continue
                for stat in props.sheet_stats(league, p["pos"]):
                    proj = learn.adjust(league, stat, props.project(league, pbook.log(p["id"]), stat, ef))
                    if not proj or proj["mean"] < 0.3:
                        continue
                    if stat == "anytime_td":  # one-sided market: show P(score) and fair odds instead
                        p_td = props.model_probs(proj, 0.5)[0]
                        fair, over_at, under_at = f"{p_td:.0%} ({prob_to_american(p_td):+d})", None, None
                    else:
                        fair = props.fair_line(proj)
                        over_at, under_at = props.threshold_lines(proj, target)
                    rows.append(dict(game=g["name"], event_id=g["event_id"], start=g["date"], athlete_id=p["id"],
                                     team=g["home_abbr"] if tid == g["home"] else g["away_abbr"],
                                     player=p["name"], stat=stat, proj=proj["mean"], sd=proj["sd"],
                                     fair=fair, over_at=over_at, under_at=under_at,
                                     last5=proj["last5"], status=injury["status"] if injury else ""))
    return rows


def run(league: str, date: str | None, odds_key: str | None, lines_csv: str | None, want_props: bool,
        max_events: int, per_team: int, sheet: bool, budget_share: float = 1.0) -> dict:
    now = datetime.now(timezone.utc)
    games_all = espn.slate(league, date)
    games = [g for g in games_all if g["state"] == "pre"]
    res = {"league": league, "generated": now, "games": games, "skipped_started": len(games_all) - len(games),
           "game_bets": [], "prop_bets": [], "ud_legs": [], "entries": [], "sheet": [], "warnings": []}
    if not games:
        res["warnings"].append("No upcoming games on this slate (try --date YYYYMMDD).")
        return res
    model = ratings.build(league, now)
    res["model"] = model
    inj = espn.injuries(league)
    consensus = {}  # multi-book game lines cost credits; ESPN already gives DraftKings' lines for free
    pbook = props.PlayerBook(league, espn.current_season(league))
    pbook.load_teams({t for g in games for t in (g["home"], g["away"])})
    try:
        inj_adj, inj_desc = injuries.team_adjustments(league, games, inj, pbook, model)
    except Exception as e:  # never lose the card over the injury layer
        inj_adj, inj_desc = {}, {}
        res["warnings"].append(f"injury adjustment skipped: {e}")
    res["game_bets"] = game_bets(league, games, model, consensus, inj_adj, inj_desc)

    if want_props:
        quotes = []
        if lines_csv:
            quotes += load_lines_csv(lines_csv, league)
        if odds_key:
            tm = espn.teams(league)
            ours = {(oddsapi.nickname(tm[g["home"]]["name"]), oddsapi.nickname(tm[g["away"]]["name"])) for g in games
                    if g["home"] in tm and g["away"] in tm}
            markets = oddsapi.DEFAULT_PROP_MARKETS[league]
            cost = oddsapi.prop_cost(markets)
            budget = int(oddsapi.allowance() * budget_share)
            fetched = []
            try:
                soon = now + timedelta(hours=30)
                evs = [e for e in oddsapi.events(league, odds_key)  # free call
                       if (oddsapi.nickname(e["home_team"]), oddsapi.nickname(e["away_team"])) in ours
                       and datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= soon]
                reused = 0
                for e in sorted(evs, key=lambda e: e["commence_time"])[:max_events]:   # earliest kickoffs first
                    saved_q = oddsapi.cached_event(league, e["id"])   # already paid for: no credits
                    if saved_q is not None:
                        fetched += saved_q
                        reused += 1
                        continue
                    if budget < cost:
                        res["warnings"].append(f"Out of Odds API credits for today: props skipped for games "
                                               f"from {e['commence_time'][:16].replace('T', ' ')} UTC onward.")
                        break
                    q = oddsapi.event_props(league, odds_key, e["id"], markets)
                    oddsapi.spend(cost)
                    budget -= cost
                    oddsapi.store_event(league, e["id"], q)
                    fetched += q
                if reused:
                    res["warnings"].append(f"{reused} game(s) reused prop lines fetched earlier (saves Odds API credits); "
                                           f"re-check prices in the app.")
            except Exception as e:
                res["warnings"].append(f"Odds API props failed: {e}")
            if fetched:
                oddsapi.save_quotes(league, fetched)
                quotes += fetched
            else:
                saved, when = oddsapi.load_quotes(league)
                if saved:
                    quotes += saved
                    res["warnings"].append(f"Prop lines reused from {when[:16].replace('T', ' ')} UTC to save "
                                           f"Odds API credits; re-check prices in the app.")
        if quotes:
            dk, legs, warn = prop_bets(league, games, model, pbook, quotes, inj)
            res["prop_bets"], res["ud_legs"] = dk, legs
            res["entries"] = best_entries(legs)
            res["warnings"] += warn[:15] + ([f"... and {len(warn) - 15} more"] if len(warn) > 15 else [])
        if sheet:
            res["sheet"] = projection_sheet(league, games, model, pbook, inj, per_team, ud_breakeven(3))
    return res
