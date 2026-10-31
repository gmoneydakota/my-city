#!/usr/bin/env python3
"""Hourly check for recurring Agent City jobs (free: no model calls).

Reads schedules.json, opens a job issue for every schedule that is due, marks it as run for
today, and prints the list for the workflow to run through city-job.yml.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCHEDULES = ROOT / "schedules.json"


def due(s: dict, now: datetime) -> bool:
    try:
        local = now.astimezone(ZoneInfo(s.get("tz") or "UTC"))
    except Exception:  # noqa: BLE001
        local = now
    hh, mm = (int(x) for x in s.get("time", "08:00").split(":"))
    return (local.weekday() in s.get("days", [])
            and (local.hour, local.minute) >= (hh, mm)
            and s.get("last_run") != local.date().isoformat()), local.date().isoformat()


def main():
    try:
        data = json.loads(SCHEDULES.read_text())
    except Exception:  # noqa: BLE001
        data = {"schedules": []}
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    now = datetime.now(timezone.utc)
    runs = []
    for s in data["schedules"]:
        is_due, today = due(s, now)
        if not is_due:
            continue
        title = f"[city] 🔁 {s['title']}"[:200]
        body = (f"Scheduled run of recurring job #{s['id']} for @{owner}\n\nAgent: {s.get('agent', 'auto')}\n"
                f"<!-- scheduled -->\n\n{s['request']}")
        p = subprocess.run(["gh", "api", "-X", "POST", f"repos/{os.environ['GITHUB_REPOSITORY']}/issues",
                            "-f", f"title={title}", "-f", f"body={body}", "-f", "labels[]=city-job",
                            "--jq", ".number"], text=True, capture_output=True)
        if p.returncode != 0:
            print(f"could not open issue for schedule {s['id']}: {p.stderr}")
            continue
        s["last_run"] = today
        runs.append({"number": p.stdout.strip(), "title": title, "body": body})
        print(f"due: schedule {s['id']} -> issue #{runs[-1]['number']}")
    if runs:
        SCHEDULES.write_text(json.dumps(data, indent=2) + "\n")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"runs={json.dumps(runs)}\n")
    print(f"{len(runs)} job(s) due")


if __name__ == "__main__":
    main()
