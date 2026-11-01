#!/usr/bin/env python3
"""The city's second brain: turns skills, agents, tools and job history into one web. Free: no model calls.

    python3 scripts/brain.py            # rebuild brain/brain.json (the web the Brain building shows) + brain/INDEX.md
    python3 scripts/brain.py --check    # also exit 1 if a skill is malformed or links to a skill that doesn't exist

Sources (nothing here is hand-maintained except the skills):
    brain/skills/<slug>.md          skills: frontmatter (title, tags, agents, learned_from, related) + Markdown body.
                                    Agents add and improve these themselves (see brain/skills/learn-a-skill.md).
    .claude/agents/*.md, agents/*.md  the agents
    scripts/*.py, cad/, bets/       the tools the agents use
    outputs/job-*/                  history: every job (job.json + README.md)

brain/INDEX.md is the short version agents read at the start of a job; scripts/city_job.py puts it in their prompt.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = ROOT / "brain"
SKILLS = BRAIN / "skills"
OUT_JSON = BRAIN / "brain.json"
OUT_INDEX = BRAIN / "INDEX.md"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
TOOL_RE = re.compile(r"scripts/([a-z0-9_]+)\.py")
# tools that aren't a single script, with the words that mean a skill uses them
APPS = {
    "cad-studio": ("CAD Studio", "cad/", "Opens and checks 3D models (model.json)", re.compile(r"\bcad/|CAD Studio|model\.json")),
    "bets-model": ("Betting model", "bets/", "Self-learning NFL/NBA model behind the Lucky Tower", re.compile(r"\bbets/")),
    "watchlist": ("Watchlist", "watchlist.json", "Tickers the free daily market scan follows", re.compile(r"watchlist\.json")),
}


def frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {k.lower(): v.strip() for k, v in re.findall(r"^([A-Za-z_]+):[ \t]*(.*)$", m.group(1), re.M)}
    return meta, m.group(2).strip()


def split_list(v: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;]", v or "") if x.strip()]


def first_doc_line(py: Path) -> str:
    m = re.search(r'^(?:#![^\n]*\n)?\s*(?:"""|\'\'\')\s*(.+?)\s*$', py.read_text(errors="replace"), re.M)
    return m.group(1).rstrip('."') if m else ""


def job_title(readme: str, n: int) -> str:
    for line in readme.splitlines():
        s = line.strip()
        if not s:
            continue
        h = re.match(r"^#+\s*(.+)$", s)
        text = h.group(1) if h else s
        text = re.sub(r"^Job\s*#?\s*\d+\s*[:·\-–]?\s*", "", text).strip()
        text = re.sub(r"[*_`]", "", text).strip()
        if text and not re.fullmatch(r"\(?Job\s*#?\d+\)?", text, re.I):
            return text[:90] + ("…" if len(text) > 90 else "")
    return f"Job #{n}"


def load_skills(problems: list[str]) -> list[dict]:
    skills = []
    for p in sorted(SKILLS.glob("*.md")):
        slug = p.stem
        meta, body = frontmatter(p.read_text(errors="replace"))
        if not SLUG_RE.match(slug):
            problems.append(f"{p.name}: file name must be a short kebab-case slug")
            continue
        if not meta.get("title"):
            problems.append(f"{p.name}: missing --- frontmatter --- with a title")
        skills.append({
            "slug": slug, "title": meta.get("title") or slug.replace("-", " ").capitalize(),
            "tags": [t.lower() for t in split_list(meta.get("tags", ""))],
            "agents": [a.lower() for a in split_list(meta.get("agents", ""))],
            "jobs": [int(x) for x in re.findall(r"\d+", meta.get("learned_from", ""))],
            "related": [r.lower() for r in split_list(meta.get("related", ""))],
            "body": body[:6000], "path": f"brain/skills/{p.name}",
        })
    return skills


def load_agents() -> dict[str, dict]:
    agents = {}
    for d in (ROOT / "agents", ROOT / ".claude" / "agents"):   # .claude/agents wins on a name clash
        for p in sorted(d.glob("*.md")):
            meta, body = frontmatter(p.read_text(errors="replace"))
            agents[p.stem] = {"name": p.stem, "model": meta.get("model", "sonnet"), "description": meta.get("description", ""),
                              "body": body[:1500], "path": str(p.relative_to(ROOT))}
    return agents


def load_jobs() -> list[dict]:
    jobs = []
    for d in (ROOT / "outputs").glob("job-*"):
        m = re.fullmatch(r"job-(\d+)", d.name)
        if not m or not d.is_dir():
            continue
        n = int(m.group(1))
        try:
            meta = json.loads((d / "job.json").read_text())
        except Exception:  # noqa: BLE001  (job still running, or an old job without metadata)
            meta = {}
        readme = (d / "README.md").read_text(errors="replace") if (d / "README.md").exists() else ""
        jobs.append({"n": n, "title": job_title(readme, n), "agent": meta.get("agent"), "mode": meta.get("mode") or "make",
                     "builds_on": meta.get("builds_on"), "finished": (meta.get("finished_at") or "")[:10],
                     "has_page": bool(meta.get("has_page")), "has_model": bool(meta.get("has_model")),
                     "body": readme[:1800]})
    return sorted(jobs, key=lambda j: j["n"])


def load_tools() -> dict[str, dict]:
    tools = {}
    for p in sorted((ROOT / "scripts").glob("*.py")):
        tools[p.stem] = {"label": f"{p.stem}.py", "path": f"scripts/{p.name}", "summary": first_doc_line(p),
                         "match": re.compile(rf"scripts/{re.escape(p.stem)}\.py")}
    for key, (label, path, summary, rx) in APPS.items():
        if (ROOT / path).exists():
            tools[key] = {"label": label, "path": path, "summary": summary, "match": rx}
    return tools


def build() -> tuple[dict, list[str]]:
    problems: list[str] = []
    skills, agents, jobs, tools = load_skills(problems), load_agents(), load_jobs(), load_tools()
    slugs = {s["slug"] for s in skills}
    job_ns = {j["n"] for j in jobs}
    nodes, links, seen = [], [], set()

    def link(a: str, b: str, kind: str):
        key = (min(a, b), max(a, b), kind)
        if a != b and key not in seen:
            seen.add(key)
            links.append({"source": a, "target": b, "kind": kind})

    runs = {}
    for j in jobs:
        if j["agent"]:
            runs[j["agent"]] = runs.get(j["agent"], 0) + 1
    for a in agents.values():
        nodes.append({"id": f"agent:{a['name']}", "type": "agent", "label": a["name"].capitalize(), "model": a["model"],
                      "summary": a["description"], "body": a["body"], "path": a["path"], "uses": runs.get(a["name"], 0)})
    for key, t in tools.items():
        nodes.append({"id": f"tool:{key}", "type": "tool", "label": t["label"], "summary": t["summary"], "path": t["path"]})

    tag_count: dict[str, int] = {}
    for s in skills:
        for t in s["tags"]:
            tag_count[t] = tag_count.get(t, 0) + 1
    topics = sorted(t for t, c in tag_count.items() if c >= 2)   # a tag only becomes a node when it joins skills
    for t in topics:
        nodes.append({"id": f"topic:{t}", "type": "topic", "label": t, "summary": f"{tag_count[t]} skills tagged {t}"})

    for s in skills:
        sid = f"skill:{s['slug']}"
        nodes.append({"id": sid, "type": "skill", "label": s["title"], "summary": ", ".join(s["tags"]), "body": s["body"],
                      "path": s["path"], "tags": s["tags"]})
        for r in s["related"]:
            if r in slugs:
                link(sid, f"skill:{r}", "related")
            else:
                problems.append(f"{s['slug']}.md: related skill '{r}' doesn't exist")
        for a in s["agents"]:
            if a in agents:
                link(sid, f"agent:{a}", "used by")
            else:
                problems.append(f"{s['slug']}.md: unknown agent '{a}'")
        for n in s["jobs"]:
            if n in job_ns:
                link(sid, f"job:{n}", "learned from")
        for t in s["tags"]:
            if t in topics:
                link(sid, f"topic:{t}", "topic")
        for key, t in tools.items():
            if t["match"].search(s["body"]):
                link(sid, f"tool:{key}", "uses tool")

    for j in jobs:
        jid = f"job:{j['n']}"
        nodes.append({"id": jid, "type": "job", "label": f"#{j['n']} {j['title']}", "summary": f"{j['agent'] or '?'} · {j['mode']} · {j['finished'] or 'running'}",
                      "body": j["body"], "path": f"outputs/job-{j['n']}/", "n": j["n"], "mode": j["mode"],
                      "has_page": j["has_page"], "has_model": j["has_model"], "finished": j["finished"]})
        if j["agent"] in agents:
            link(jid, f"agent:{j['agent']}", "done by")
        if j["builds_on"] in job_ns:
            link(jid, f"job:{j['builds_on']}", "builds on")
        if j["has_model"] and "cad-studio" in tools:
            link(jid, "tool:cad-studio", "uses tool")
        if "bets-model" in tools and re.search(r"\bbet(s|ting)?\b", j["body"][:600], re.I):
            link(jid, "tool:bets-model", "uses tool")
        for key, t in tools.items():   # scripts a job's README says it used
            if key not in APPS and t["match"].search(j["body"]):
                link(jid, f"tool:{key}", "uses tool")

    data = {"format": "agent-city-brain/1",
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": {"skills": len(skills), "agents": len(agents), "jobs": len(jobs), "tools": len(tools),
                       "topics": len(topics), "links": len(links)},
            "nodes": nodes, "links": links, "problems": problems}
    return data, problems


def index_md(data: dict) -> str:
    by = {t: [n for n in data["nodes"] if n["type"] == t] for t in ("skill", "tool", "job")}
    skill_link = {}
    for l in data["links"]:
        for a, b in ((l["source"], l["target"]), (l["target"], l["source"])):
            if a.startswith("skill:") and b.startswith("agent:"):
                skill_link.setdefault(a, []).append(b[6:])
    lines = ["# The city's second brain (generated by scripts/brain.py, do not edit)", "",
             "Skills = how-tos the agents learned. Read the ones that match your job in brain/skills/<slug>.md before",
             "you start. If you work out something reusable that isn't here, add a skill (see learn-a-skill).", "",
             "## Skills"]
    for s in by["skill"]:
        who = ", ".join(sorted(skill_link.get(s["id"], [])))
        lines.append(f"- {s['id'][6:]}: {s['label']} [{s['summary']}]" + (f" (agents: {who})" if who else ""))
    lines += ["", "## Tools"] + [f"- {t['path']}: {t['summary']}" for t in by["tool"]]
    recent = by["job"][-12:]
    lines += ["", "## Recent jobs (outputs/job-N/)"] + [f"- {j['label']} ({j['summary']})" for j in recent]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    data, problems = build()
    OUT_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    OUT_INDEX.write_text(index_md(data))
    c = data["counts"]
    print(f"brain: {c['skills']} skills, {c['agents']} agents, {c['tools']} tools, {c['jobs']} jobs, {c['links']} links")
    for p in problems:
        print(f"  ! {p}")
    return 1 if check and problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
