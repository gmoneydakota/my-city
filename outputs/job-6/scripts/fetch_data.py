"""Download + cache historical data into outputs/job-6/data (skips files already present)."""
import csv
import datetime as dt
import io
import json
import time
import urllib.request as u
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data"
D.mkdir(exist_ok=True)
KEEP = ["player_id", "player_display_name", "position", "season", "week", "season_type", "team", "opponent_team",
        "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
        "carries", "rushing_yards", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds",
        "target_share", "air_yards_share", "receiving_air_yards"]


def get(url, t=60):
    return u.urlopen(u.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=t).read()


def save(name, url, trim=False):
    p = D / name
    if p.exists() and p.stat().st_size > 1000:
        return
    raw = get(url)
    if trim:
        rows = csv.DictReader(io.StringIO(raw.decode()))
        buf = io.StringIO()
        w = csv.DictWriter(buf, KEEP, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            if r["position"] in ("QB", "RB", "WR", "TE"):
                w.writerow(r)
        raw = buf.getvalue().encode()
    p.write_bytes(raw)
    print("saved", name, p.stat().st_size)
    time.sleep(0.5)


save("nfl_games.csv", "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv")
for y in range(2020, 2027):
    try:
        save("nfl_player_week_%d.csv" % y,
             "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_%d.csv" % y,
             trim=True)
    except Exception as e:
        print("skip", y, e)

# NBA games from the ESPN scoreboard, one day per request (cached). Seasons named by end year.
SEASONS = {2023: ("20221018", "20230411"), 2024: ("20231024", "20240414"),
           2025: ("20241022", "20250413"), 2026: ("20251021", "20261031")}
for season, (a, b) in SEASONS.items():
    p = D / ("nba_games_%d.json" % season)
    if p.exists():
        continue
    d0, d1 = dt.datetime.strptime(a, "%Y%m%d"), dt.datetime.strptime(b, "%Y%m%d")
    out, fails = {}, 0
    while d0 <= d1:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=" + d0.strftime("%Y%m%d")
        try:
            ev = json.loads(get(url))["events"]
        except Exception as ex:
            fails += 1
            ev = []
        for x in ev:
            c = x["competitions"][0]
            if x["season"]["type"] != 2 or not c["status"]["type"]["completed"]:
                continue
            h = next(t for t in c["competitors"] if t["homeAway"] == "home")
            a_ = next(t for t in c["competitors"] if t["homeAway"] == "away")
            out[x["id"]] = {"id": x["id"], "date": x["date"], "home": h["team"]["abbreviation"],
                            "away": a_["team"]["abbreviation"], "hs": float(h["score"]), "as": float(a_["score"])}
        d0 += dt.timedelta(days=1)
        time.sleep(0.25)
    if out and fails < 10:
        p.write_text(json.dumps(sorted(out.values(), key=lambda r: r["date"])))
    print("nba", season, len(out), "failed days", fails)
