#!/usr/bin/env python3
"""Run the Trading Floor: three competing paper traders. Pure Python, zero Claude usage.

    python3 scripts/trading_floor.py                 # one live run (the workflow does this on a schedule)
    python3 scripts/trading_floor.py --demo 40       # rebuild trading/demo with 40 synthetic trading days
    python3 scripts/trading_floor.py --manage        # quick position check (every 15 min between scans)
    python3 scripts/trading_floor.py --phase post    # force an end-of-day pass (testing)

Live runs read and write trading/data/. Demo runs write only trading/demo/ and never touch live data.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from floor import clock  # noqa: E402
from floor.engine import Floor, Store  # noqa: E402
from floor.providers import DemoProvider, LiveProvider  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR, DEMO_DIR = ROOT / "trading" / "data", ROOT / "trading" / "demo"
SLOTS = [5, 65, 125, 185, 245, 305, 365]   # full scans: minutes after the open (9:35, 10:35 ... 15:35 ET)
MANAGE = [m for h in range(0, 7) for m in (20 + 60 * h, 35 + 60 * h, 50 + 60 * h) if m < 385]   # between scans: stops/targets/trailing every 15 min


def run_demo(days: int, out: Path = DEMO_DIR, seed: int = 7, log=print):
    if out.exists():
        shutil.rmtree(out)
    prov = DemoProvider(seed=seed, sim_days=days)
    floor = Floor(prov, Store(out), demo=True)
    sim = [d for d in prov.days if prov.first_sim and d >= prov.first_sim]
    quiet = lambda *_: None
    for d in sim:
        for m in sorted(SLOTS + MANAGE + [None], key=lambda x: 999 if x is None else x):
            if m is None:
                t = datetime(d.year, d.month, d.day, 16, 20, tzinfo=clock.ET)
            else:
                t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=clock.ET) + timedelta(minutes=m)
            prov.set_time(t)
            floor.run(t.astimezone(timezone.utc), manage_only=(m in MANAGE), log=quiet)
        log(f"  simulated {d}")
    return floor


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", type=int, metavar="DAYS", help="rebuild the synthetic demo dataset")
    ap.add_argument("--phase", choices=["open", "post"], help="force a phase (testing only)")
    ap.add_argument("--now", help="pretend it is this ISO time (testing only)")
    ap.add_argument("--manage", action="store_true", help="light run: only refresh held positions (stops, targets, trailing); no new trades")
    args = ap.parse_args()
    if args.demo:
        run_demo(args.demo)
        print(f"demo data written to {DEMO_DIR}")
        return 0
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    prov = LiveProvider(LIVE_DIR)
    res = Floor(prov, Store(LIVE_DIR)).run(now, force_phase=args.phase, manage_only=args.manage)
    print(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
