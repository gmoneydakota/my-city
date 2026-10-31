#!/usr/bin/env python3
"""Snapshot every job's files into outputs/job-9/manifest.json.

The Products page reads the live file list from GitHub's API. If that is unavailable
(rate limit, offline, opened from disk) it falls back to this snapshot instead.

    python3 outputs/job-9/build_manifest.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUTS = HERE.parent
JOB_DIR = re.compile(r"^job-(\d+)$")


def readme_title(readme: Path) -> str:
    """First markdown heading of a README, or '' if there isn't one."""
    try:
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^#{1,3}\s+(.+?)\s*#*\s*$", line)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return ""


def main() -> None:
    jobs = []
    for d in OUTPUTS.iterdir():
        m = JOB_DIR.match(d.name)
        if not d.is_dir() or not m:
            continue
        files = []
        for f in sorted(d.rglob("*")):
            rel = f.relative_to(d)
            # skip hidden files/folders and Python caches; they are never products
            if not f.is_file() or any(p.startswith(".") or p == "__pycache__" for p in rel.parts):
                continue
            files.append({"path": rel.as_posix(), "size": f.stat().st_size})
        meta = {}
        if (d / "job.json").is_file():
            try:
                meta = json.loads((d / "job.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        jobs.append({
            "job": int(m.group(1)),
            "title": readme_title(d / "README.md"),
            "meta": meta,
            "files": files,
        })
    jobs.sort(key=lambda j: j["job"], reverse=True)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "jobs": jobs}
    (HERE / "manifest.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote manifest.json with {len(jobs)} jobs")


if __name__ == "__main__":
    main()
