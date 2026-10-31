"""Self-learning: record every prediction, grade it once the game is final, retune the model.

Runs every day in `python3 bets.py daily` (plain Python, no AI usage):

1. record()  - after each card, store EVERY priced bet (not just the picks) and every player
               projection, so there's lots to learn from each day.
2. grade()   - when games are final, fill in what actually happened.
3. fit()     - retune, and write learned.json:
     * game_weights / prop_weight: how much to trust our model vs the betting market, chosen to
       minimise log-loss on graded bets, shrunk toward the default until there's enough data.
     * calibration[league:stat]: projection scale (are we too high/low?) and spread scale
       (are we over/under-confident?) per stat, from projected vs actual.
   Every change is written as a plain-English lesson to history/learning_log.json.

engine.py reads learned.json through game_weight(), prop_weight() and adjust().
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from datetime import datetime, timedelta, timezone

from . import espn
from .common import ROOT, DataError, get_json

HIST = ROOT / "history"
SHADOW = HIST / "shadow_bets.csv"
PROJ = HIST / "projections_log.csv"
LOG = HIST / "learning_log.json"
LEARNED = ROOT / "learned.json"

SHADOW_FIELDS = ["date", "league", "event_id", "start", "kind", "selection", "line", "price",
                 "p_model", "p_market", "p", "ev", "athlete_id", "stat", "side", "result"]
PROJ_FIELDS = ["date", "league", "event_id", "start", "athlete_id", "player", "stat", "proj", "sd", "actual"]

DEFAULT_GAME_W = 0.30
DEFAULT_PROP_W = 0.50
MIN_N_WEIGHT = 40       # graded bets before a weight is allowed to move at all
SHRINK_WEIGHT = 150     # pseudo-count pulling learned weights toward the default
MIN_N_CAL = 25          # graded projections per stat before calibrating it
SHRINK_CAL = 80
KEEP_DAYS = 400

_cache = None


def _learned() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(LEARNED.read_text())
        except Exception:  # noqa: BLE001 - first run, or a bad file: fall back to defaults
            _cache = {}
    return _cache


def game_weight(kind: str, default: float) -> float:
    return float(_learned().get("game_weights", {}).get(kind, default))


def prop_weight(default: float) -> float:
    return float(_learned().get("prop_weight", default))


def adjust(league: str, stat: str, proj: dict | None) -> dict | None:
    """Apply learned per-stat calibration to a projection (mean and spread)."""
    if not proj:
        return proj
    cal = _learned().get("calibration", {}).get(f"{league}:{stat}")
    if not cal:
        return proj
    out = dict(proj)
    out["mean"] = proj["mean"] * cal.get("scale", 1.0)
    out["sd"] = proj["sd"] * cal.get("sd_scale", 1.0)
    return out


# --------------------------------------------------------------------------- record

def _read(path, fields):
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [{k: r.get(k, "") for k in fields} for r in csv.DictReader(f)]


def _write(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)


def _f(x, nd=4):
    return "" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def record(res: dict) -> tuple[int, int]:
    """Store every priced bet and projection from this card. Later runs before tip-off overwrite
    earlier ones (closer to game time = better information)."""
    today = datetime.now(timezone.utc).date().isoformat()
    lg = res["league"]
    shadow = {(r["event_id"], r["selection"]): r for r in _read(SHADOW, SHADOW_FIELDS)}
    n_b = 0
    for b in res["game_bets"] + res["prop_bets"]:
        key = (b["event_id"], b["selection"])
        if key in shadow and shadow[key]["result"]:
            continue
        shadow[key] = {"date": today, "league": lg, "event_id": b["event_id"], "start": b["start"].isoformat(),
                       "kind": b["kind"], "selection": b["selection"], "line": _f(b.get("line")),
                       "price": _f(b.get("price")), "p_model": _f(b.get("p_model")), "p_market": _f(b.get("p_market")),
                       "p": _f(b["p"]), "ev": _f(b["ev"]), "athlete_id": b.get("athlete_id", ""),
                       "stat": b.get("stat", ""), "side": b.get("side", ""), "result": ""}
        n_b += 1
    projs = {(r["event_id"], r["athlete_id"], r["stat"]): r for r in _read(PROJ, PROJ_FIELDS)}
    n_p = 0
    for r in res["sheet"]:
        if not r.get("athlete_id") or r["stat"] == "anytime_td":
            continue
        key = (r["event_id"], r["athlete_id"], r["stat"])
        if key in projs and projs[key]["actual"]:
            continue
        projs[key] = {"date": today, "league": lg, "event_id": r["event_id"], "start": r["start"].isoformat(),
                      "athlete_id": r["athlete_id"], "player": r["player"], "stat": r["stat"],
                      "proj": _f(r["proj"], 3), "sd": _f(r["sd"], 3), "actual": ""}
        n_p += 1
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).date().isoformat()
    _write(SHADOW, SHADOW_FIELDS, [r for r in shadow.values() if r["date"] >= cutoff])
    _write(PROJ, PROJ_FIELDS, [r for r in projs.values() if r["date"] >= cutoff])
    return n_b, n_p


# --------------------------------------------------------------------------- grade

def _final(league, event_id, memo):
    if (league, event_id) in memo:
        return memo[(league, event_id)]
    try:
        d = get_json(f"{espn.SITE}/{espn._path(league)}/summary", {"event": event_id}, ttl_hours=2)
        comp = d["header"]["competitions"][0]
        sc = None
        if comp["status"]["type"].get("completed"):
            sc = {c["homeAway"]: (float(c["score"]), c["team"]["abbreviation"]) for c in comp["competitors"]}
    except (DataError, KeyError, IndexError, ValueError):
        sc = None
    memo[(league, event_id)] = sc
    return sc


def _game_result(kind, selection, line, sc):
    (hs, ha), (as_, aa) = sc["home"], sc["away"]
    if kind == "Total":
        tot, ln = hs + as_, float(line)
        diff = tot - ln if selection.startswith("Over") else ln - tot
    else:
        team = selection.split()[0]
        margin = hs - as_ if team == ha else as_ - hs
        diff = margin + (float(line) if kind == "Spread" and line else 0)
    return "W" if diff > 0 else "L" if diff < 0 else "P"


def _stat_value(league, athlete_id, event_id, stat, logs):
    from .props import STATS
    if athlete_id not in logs:
        try:
            logs[athlete_id] = espn.gamelog(league, athlete_id)
        except Exception:  # noqa: BLE001
            logs[athlete_id] = []
    row = next((g for g in logs[athlete_id] if g.get("event_id") == event_id), None)
    if row is None:
        return None, False
    try:
        return STATS[league][stat][0](row), True
    except (KeyError, TypeError):
        return None, True


def grade() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    memo, logs = {}, {}
    shadow = _read(SHADOW, SHADOW_FIELDS)
    n_b = 0
    for r in shadow:
        if r["result"] or datetime.fromisoformat(r["start"]) > now - timedelta(hours=3):
            continue
        if r["kind"] in ("ML", "Spread", "Total"):
            sc = _final(r["league"], r["event_id"], memo)
            if sc:
                r["result"] = _game_result(r["kind"], r["selection"], r["line"], sc)
                n_b += 1
        elif r["kind"] == "Prop" and r["athlete_id"]:
            v, played = _stat_value(r["league"], r["athlete_id"], r["event_id"], r["stat"], logs)
            if v is not None:
                diff = (v - float(r["line"])) * (1 if r["side"] == "over" else -1)
                r["result"] = "W" if diff > 0 else "L" if diff < 0 else "P"
                n_b += 1
            elif not played and datetime.fromisoformat(r["start"]) < now - timedelta(days=2):
                r["result"] = "VOID"
    _write(SHADOW, SHADOW_FIELDS, shadow)

    projs = _read(PROJ, PROJ_FIELDS)
    n_p = 0
    for r in projs:
        if r["actual"] or datetime.fromisoformat(r["start"]) > now - timedelta(hours=3):
            continue
        v, played = _stat_value(r["league"], r["athlete_id"], r["event_id"], r["stat"], logs)
        if v is not None:
            r["actual"] = f"{float(v):g}"
            n_p += 1
        elif not played and datetime.fromisoformat(r["start"]) < now - timedelta(days=2):
            r["actual"] = "DNP"
    _write(PROJ, PROJ_FIELDS, projs)
    return n_b, n_p


# --------------------------------------------------------------------------- fit

def _logloss(rows, w):
    tot = 0.0
    for pm, pk, y in rows:
        p = min(max(w * pm + (1 - w) * pk, 1e-4), 1 - 1e-4)
        tot -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return tot / len(rows)


def _fit_weight(rows, default):
    """rows: (p_model, p_market, won). Best blend weight, shrunk toward default by sample size."""
    if len(rows) < MIN_N_WEIGHT:
        return default, None
    grid = [i / 20 for i in range(21)]
    best = min(grid, key=lambda w: _logloss(rows, w))
    n = len(rows)
    w = default + (best - default) * n / (n + SHRINK_WEIGHT)
    return round(w, 3), {"n": n, "raw_best": best, "logloss_model": round(_logloss(rows, 1.0), 4),
                         "logloss_market": round(_logloss(rows, 0.0), 4), "logloss_blend": round(_logloss(rows, w), 4)}


def _fit_calibration(rows):
    """rows: (proj, sd, actual). Returns scale for the mean and for the spread."""
    if len(rows) < MIN_N_CAL:
        return None
    n = len(rows)
    sp, sa = sum(r[0] for r in rows), sum(r[2] for r in rows)
    raw_scale = min(max(sa / sp, 0.8), 1.2) if sp > 0 else 1.0
    z = [(a - p * raw_scale) / s for p, s, a in rows if s > 0]
    raw_sd = min(max(statistics.pstdev(z) if len(z) > 1 else 1.0, 0.7), 1.5)
    k = n / (n + SHRINK_CAL)
    return {"scale": round(1 + (raw_scale - 1) * k, 4), "sd_scale": round(1 + (raw_sd - 1) * k, 4), "n": n,
            "avg_proj": round(sp / n, 2), "avg_actual": round(sa / n, 2)}


def _record(rows):
    w = sum(r["result"] == "W" for r in rows)
    l_ = sum(r["result"] == "L" for r in rows)
    return {"w": w, "l": l_, "p": sum(r["result"] == "P" for r in rows),
            "hit_rate": round(w / (w + l_), 4) if w + l_ else None}


def _roi(rows):
    staked = profit = 0.0
    for r in rows:
        if r["result"] not in ("W", "L") or not r["price"]:
            continue
        price = float(r["price"])
        dec = 1 + (price / 100 if price > 0 else 100 / -price)
        staked += 1
        profit += dec - 1 if r["result"] == "W" else -1
    return round(profit / staked, 4) if staked else None


def fit() -> dict:
    old = dict(_learned())
    shadow = [r for r in _read(SHADOW, SHADOW_FIELDS) if r["result"] in ("W", "L")]
    lessons = []
    new = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "game_weights": {},
           "fit_stats": {}, "calibration": {}}

    for kind in ("ML", "Spread", "Total"):
        rows = [(float(r["p_model"]), float(r["p_market"]), r["result"] == "W") for r in shadow
                if r["kind"] == kind and r["p_model"] and r["p_market"]]
        prev = old.get("game_weights", {}).get(kind, DEFAULT_GAME_W)
        w, st = _fit_weight(rows, DEFAULT_GAME_W)
        new["game_weights"][kind] = w
        if st:
            new["fit_stats"][kind] = st
            if abs(w - prev) >= 0.01:
                lessons.append(f"{kind}: trusting the model {prev:.0%} → {w:.0%} (vs the market) after {st['n']} graded "
                               f"bets — the {'model' if st['logloss_model'] < st['logloss_market'] else 'market'} "
                               f"has been the better predictor so far.")
        else:
            lessons_needed = MIN_N_WEIGHT - len(rows)
            new["fit_stats"][kind] = {"n": len(rows), "needs": lessons_needed}

    prop_rows = [(float(r["p_model"]), float(r["p_market"]), r["result"] == "W") for r in shadow
                 if r["kind"] == "Prop" and r["p_model"] and r["p_market"]]
    pw, pst = _fit_weight(prop_rows, DEFAULT_PROP_W)
    new["prop_weight"] = pw
    new["fit_stats"]["Prop"] = pst or {"n": len(prop_rows), "needs": MIN_N_WEIGHT - len(prop_rows)}
    if pst and abs(pw - old.get("prop_weight", DEFAULT_PROP_W)) >= 0.01:
        lessons.append(f"Player props: trusting the model {old.get('prop_weight', DEFAULT_PROP_W):.0%} → {pw:.0%} "
                       f"after {pst['n']} graded props.")

    groups = {}
    for r in _read(PROJ, PROJ_FIELDS):
        if r["actual"] in ("", "DNP"):
            continue
        try:
            groups.setdefault(f"{r['league']}:{r['stat']}", []).append(
                (float(r["proj"]), float(r["sd"]), float(r["actual"])))
        except ValueError:
            continue
    for key, rows in sorted(groups.items()):
        cal = _fit_calibration(rows)
        if not cal:
            continue
        new["calibration"][key] = cal
        prev = old.get("calibration", {}).get(key, {"scale": 1.0, "sd_scale": 1.0})
        lg, stat = key.split(":")
        if abs(cal["scale"] - prev.get("scale", 1)) >= 0.01:
            direction = "too low" if cal["scale"] > 1 else "too high"
            lessons.append(f"{lg.upper()} {stat}: projections ran {direction} (avg {cal['avg_proj']} projected vs "
                           f"{cal['avg_actual']} actual over {cal['n']} players) → now scaled ×{cal['scale']:.3f}.")
        if abs(cal["sd_scale"] - prev.get("sd_scale", 1)) >= 0.02:
            conf = "overconfident" if cal["sd_scale"] > 1 else "underconfident"
            lessons.append(f"{lg.upper()} {stat}: was {conf} about player swings → uncertainty ×{cal['sd_scale']:.3f}.")

    all_rows = [r for r in _read(SHADOW, SHADOW_FIELDS) if r["result"] in ("W", "L", "P")]
    leans = [r for r in all_rows if r["ev"] and float(r["ev"]) > 0]
    new["scoreboard"] = {
        "graded_bets": len(all_rows), "graded_projections": sum(len(v) for v in groups.values()),
        "model_leans": {**_record(leans), "roi_per_bet": _roi(leans)},
        "strong_leans": {**_record([r for r in leans if float(r["ev"]) >= 0.03]),
                         "roi_per_bet": _roi([r for r in leans if float(r["ev"]) >= 0.03])},
    }
    LEARNED.write_text(json.dumps(new, indent=2) + "\n")
    global _cache
    _cache = new

    log = []
    try:
        log = json.loads(LOG.read_text())
    except Exception:  # noqa: BLE001
        pass
    entry = {"date": datetime.now(timezone.utc).date().isoformat(), "lessons": lessons or
             ["Not enough finished games yet to change anything. Still collecting results."],
             "scoreboard": new["scoreboard"]}
    log = [e for e in log if e["date"] != entry["date"]] + [entry]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(log[-120:], indent=2) + "\n")
    return {"learned": new, "lessons": entry["lessons"]}
