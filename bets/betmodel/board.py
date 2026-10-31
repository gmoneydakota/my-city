"""Writes board/latest.json: every bet the model priced today, tiered, for the city's Bets tab."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .common import ROOT

BOARD = ROOT / "board"
TIER_ORDER = {"best": 0, "lean": 1, "check": 2, "pass": 3}


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


def _bet_row(league, b, tier, bankroll, book="DraftKings"):
    return {"league": league, "tier": tier, "kind": b["kind"], "book": book, "game": b["game"],
            "start": b["start"].isoformat(), "selection": b["selection"], "odds": b.get("price"),
            "prob": _r(b["p"]), "model_prob": _r(b.get("p_model")), "market_prob": _r(b.get("p_market")),
            "ev": _r(b["ev"]), "stake": round(bankroll * b.get("kelly", 0), 2) if b["ev"] > 0 else 0,
            "note": (b.get("flag") or "") + (" " if b.get("flag") else "") + (b.get("notes") or ""),
            "model_line": b.get("model_line", ""), "proj": _r(b.get("proj"), 2)}


def build(results, bankroll: float, be3: float) -> dict:
    bets, projections, warnings = [], [], []
    for res, picks in results:
        lg = res["league"]
        best_ids = {id(b) for b in picks["game"] + picks["prop"] if not b.get("flag")}
        for b in res["game_bets"] + res["prop_bets"]:
            if id(b) in best_ids:
                tier = "best"
            elif b.get("flag") or (b["ev"] > 0.15 and b["kind"] != "Prop"):
                tier = "check"
            elif b["ev"] > 0 and b["p"] >= 0.18:
                tier = "lean"
            else:
                tier = "pass"
            bets.append(_bet_row(lg, b, tier, bankroll))
        for l in res["ud_legs"]:
            if l["p"] <= 0.5:
                continue
            bets.append({"league": lg, "tier": "best" if l["value"] >= be3 else "lean", "kind": "Underdog",
                         "book": "Underdog", "game": l["game"], "start": l["start"].isoformat(),
                         "selection": f"{l['player']} {'Higher' if l['side'] == 'over' else 'Lower'} {l['line']:g} {l['stat']}"
                                      + (f" ({l['mult']:g}x)" if l.get("mult", 1) != 1 else ""),
                         "odds": None, "prob": _r(l["p"]), "model_prob": None, "market_prob": _r(l.get("p_market_over")),
                         "ev": _r(l["value"] - be3), "stake": 0, "note": l.get("notes", ""), "proj": _r(l.get("proj"), 2)})
        for e in res["entries"]:
            bets.append({"league": lg, "tier": "best", "kind": "Entry", "book": "Underdog",
                         "game": f"{e['n']}-pick entry", "start": min(l["start"] for l in e["legs"]).isoformat(),
                         "selection": " + ".join(f"{l['player']} {'Higher' if l['side'] == 'over' else 'Lower'} "
                                                 f"{l['line']:g} {l['stat']}" for l in e["legs"]),
                         "odds": f"{e['payout']:g}x", "prob": _r(e["p_win"]), "model_prob": None, "market_prob": None,
                         "ev": _r(e["ev"]), "stake": 0, "note": "Assumes legs are independent", "proj": None})
        for r in res["sheet"]:
            projections.append({"league": lg, "game": r["game"], "start": r["start"].isoformat() if r.get("start") else None,
                                "player": r["player"], "team": r["team"], "stat": r["stat"], "proj": _r(r["proj"], 2),
                                "fair": r["fair"], "higher_if_le": r["over_at"], "lower_if_ge": r["under_at"],
                                "last5": r["last5"], "status": r["status"]})
        warnings += [f"{lg.upper()}: {w}" for w in res["warnings"]]
    bets.sort(key=lambda b: (TIER_ORDER[b["tier"]], -(b["ev"] or -9)))
    return {"bets": bets, "projections": projections, "warnings": warnings[:30]}


def write(results, learned: dict, lessons: list, record_text: str, bankroll: float, be3: float,
          errors: list[str]) -> None:
    from .learn import LOG
    data = build(results, bankroll, be3)
    try:
        log = json.loads(LOG.read_text())[-10:]
    except Exception:  # noqa: BLE001
        log = []
    data.update({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bankroll": bankroll,
        "counts": {t: sum(b["tier"] == t for b in data["bets"]) for t in TIER_ORDER},
        "record": record_text,
        "learning": {"lessons": lessons, "scoreboard": learned.get("scoreboard", {}),
                     "game_weights": learned.get("game_weights", {}), "prop_weight": learned.get("prop_weight"),
                     "calibrated_stats": len(learned.get("calibration", {})), "log": log},
        "errors": errors,
        "disclaimer": "Model estimates, not guarantees. Even good bets lose often; bet small and only what you can "
                      "afford to lose. Gambling problem? Call 1-800-GAMBLER.",
    })
    BOARD.mkdir(parents=True, exist_ok=True)
    (BOARD / "latest.json").write_text(json.dumps(data, indent=1, default=str))
