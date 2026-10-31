#!/usr/bin/env python3
"""Restarts jobs that were paused by a Claude usage limit, once the limit has reset.

Runs twice an hour from .github/workflows/city-resume.yml. It is plain Python: it uses NO Claude usage.
A paused job has the `status:paused` label and a hidden marker in its latest "Paused" comment:
    <!-- city-resume-at: 2026-10-31T20:00+00:00 -->
When that time has passed, this swaps the label to `status:working` and hands the job to city-job.yml,
which restores the saved checkpoint (branch checkpoint/job-N) and tells the agent to carry on.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

REPO = os.environ["GITHUB_REPOSITORY"]
MARK = re.compile(r"<!--\s*city-resume-at:\s*(\S+?)\s*-->")
GRACE = timedelta(minutes=3)          # let the limit really clear before restarting
FALLBACK = timedelta(hours=5, minutes=10)


def api(*args):
    p = subprocess.run(["gh", "api", *args], text=True, capture_output=True)
    if p.returncode:
        print(f"gh api {' '.join(args)} failed: {p.stderr.strip()}")
        return None
    return json.loads(p.stdout) if p.stdout.strip() else {}


def resume_time(number, updated_at):
    comments = api(f"repos/{REPO}/issues/{number}/comments?per_page=100") or []
    for c in reversed(comments):
        m = MARK.search(c.get("body") or "")
        if m:
            try:
                return datetime.fromisoformat(m.group(1)).astimezone(timezone.utc)
            except ValueError:
                break
    return datetime.fromisoformat(updated_at.replace("Z", "+00:00")) + FALLBACK


def main():
    now = datetime.now(timezone.utc)
    issues = api(f"repos/{REPO}/issues?labels=status:paused&state=open&per_page=50") or []
    runs = []
    for i in issues:
        if "pull_request" in i or i["user"]["login"] != REPO.split("/")[0]:
            continue                                   # only the owner's own jobs ever run
        at = resume_time(i["number"], i["updated_at"])
        if now < at + GRACE:
            print(f"#{i['number']} paused until {at:%Y-%m-%d %H:%M} UTC")
            continue
        # claim it first so the next check can't start it twice
        api("-X", "DELETE", f"repos/{REPO}/issues/{i['number']}/labels/status:paused")
        api("-X", "POST", f"repos/{REPO}/issues/{i['number']}/labels", "-f", "labels[]=status:working")
        api("-X", "POST", f"repos/{REPO}/issues/{i['number']}/comments", "-f",
            "body=▶️ Your usage has reset. Restarting this job from where it stopped…")
        runs.append({"number": i["number"], "title": i["title"], "body": i.get("body") or ""})
        print(f"resuming #{i['number']}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"runs={json.dumps(runs)}\n")
    print(f"{len(runs)} job(s) to resume")


if __name__ == "__main__":
    main()
