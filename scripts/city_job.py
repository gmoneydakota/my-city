#!/usr/bin/env python3
"""Runs one Agent City job inside GitHub Actions. Called by .github/workflows/city-job.yml.

    python3 scripts/city_job.py run      # route -> run agent -> maybe escalate -> write outputs
    python3 scripts/city_job.py finish   # comment on the issue, label it done, close it
    python3 scripts/city_job.py fail     # label failed + explain

Cost control, cheapest first:
  1. Routing uses keyword rules (free). Only ambiguous requests get one Haiku call.
  2. The chosen agent's own prompt becomes the system prompt, on that agent's model tier,
     so there's no extra "manager" model sitting on top burning tokens.
  3. Light/standard agents can answer `ESCALATE: <agent>` instead of struggling;
     only then is a heavier model used (one hop max).
  4. Every tier has a hard turn cap.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / ".claude" / "agents"
STATE = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "city-job.json"

TIER_OF = {"haiku": "light", "sonnet": "standard", "opus": "heavy"}
RANK = {"light": 0, "standard": 1, "heavy": 2}
MAX_TURNS = {"light": 12, "standard": 35, "heavy": 70}
# Tools an agent may use headlessly. Bash is limited to interpreters/package managers.
BASH_OK = ["Bash(python3:*)", "Bash(python:*)", "Bash(pip:*)", "Bash(pip3:*)", "Bash(node:*)",
           "Bash(npm:*)", "Bash(npx:*)", "Bash(ls:*)", "Bash(mkdir:*)", "Bash(cat:*)", "Bash(head:*)"]

# Keyword routing: (agent, pattern). First match with a unique winner skips the LLM entirely.
RULES = [
    ("quant", r"\b(stock|stocks|ticker|share price|buy signal|when to buy|sell signal|portfolio|"
              r"backtest|trading|invest|etf|crypto|bitcoin|options|dividend|earnings|market model)\b"),
    ("forge", r"\b(mcp server|mcp connector|build (a|an) connector)\b"),
    ("scout", r"\b(connector idea|what should i connect|find (an? )?(api|data source))\b"),
    ("tutor", r"^(explain|teach me|how does|what is|why does)\b"),
    ("planner", r"\b(plan|roadmap|break (this|it) down|steps to)\b"),
    ("scribe", r"\b(rewrite|proofread|reword|edit my|cover letter|email|essay|readme|summari[sz]e)\b"),
    ("runner", r"^(convert|how many|what's|whats|calculate)\b"),
    ("coder", r"\b(build|make|create|code|script|app|website|site|game|tool|bot|program|"
              r"spreadsheet|dashboard|automate|fix)\b"),
]


def sh(cmd: list[str], check=True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True, **kw)


def gh(*args: str, check=False):
    return sh(["gh", *args], check=check)


def load_agent(name: str) -> dict:
    p = AGENTS_DIR / f"{name}.md"
    if not p.exists():
        raise SystemExit(f"unknown agent: {name}")
    txt = p.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", txt, re.S)
    meta = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
    tools = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]
    return {"name": name, "model": meta.get("model", "sonnet"), "tier": TIER_OF.get(meta.get("model"), "standard"),
            "tools": tools, "prompt": m.group(2).strip(), "description": meta.get("description", "")}


def all_agents() -> dict:
    return {p.stem: load_agent(p.stem) for p in sorted(AGENTS_DIR.glob("*.md"))}


def parse_request() -> tuple[str, str | None]:
    title = os.environ.get("ISSUE_TITLE", "")
    body = os.environ.get("ISSUE_BODY", "") or ""
    forced = None
    m = re.search(r"^\s*Agent:\s*([a-z]+)\s*$", body, re.I | re.M)
    if m and m.group(1).lower() != "auto":
        forced = m.group(1).lower()
    body = re.sub(r"^\s*Agent:.*$", "", body, flags=re.I | re.M)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
    clean_title = re.sub(r"^\[city\]\s*", "", title, flags=re.I).strip()
    request = body if len(body) > len(clean_title) else f"{clean_title}\n\n{body}".strip()
    return request, forced


def route(request: str, agents: dict) -> tuple[str, str]:
    text = request.lower()
    hits = [a for a, pat in RULES if re.search(pat, text, re.M)]
    if len(hits) == 1 or (hits and hits[0] == "quant"):
        return hits[0], "keyword rules (free)"
    if hits and len(set(hits) - {"coder"}) == 0:
        return "coder", "keyword rules (free)"
    roster = "\n".join(f"- {a['name']}: {a['description']}" for a in agents.values())
    prompt = (f"Pick the single cheapest agent that can fully handle this request. Agents:\n{roster}\n\n"
              f"Request:\n<<<\n{request[:3000]}\n>>>\n\nReply with only the agent name, lowercase.")
    try:
        out = sh(["claude", "-p", prompt, "--model", "haiku", "--max-turns", "1"], timeout=120).stdout.strip().lower()
        pick = re.findall(r"[a-z]+", out)
        pick = next((p for p in pick if p in agents), None)
        if pick:
            return pick, "one Haiku routing call"
    except Exception as exc:  # noqa: BLE001
        print(f"routing call failed: {exc}", file=sys.stderr)
    return (hits[0] if hits else "planner"), "fallback"


def build_prompt(agent: dict, request: str, job: int, out_dir: str, can_write: bool) -> tuple[str, str]:
    today = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    system = agent["prompt"] + f"""

--- Agent City cloud job rules ---
Today is {today} (UTC). You are running unattended on a GitHub Actions server; nobody can answer
questions, so make sensible assumptions and list them at the end.
{"Save every file you create in " + out_dir + "/ (create it). Never edit files outside it, except watchlist.json when asked to track a ticker. Always include "
 + out_dir + "/README.md explaining what you made and exactly how to use or run it." if can_write else
 "You cannot write files; your final reply is saved as the deliverable, so make it complete and well formatted in Markdown."}
For anything time-sensitive (prices, news, versions, laws) get fresh data with your tools and state the date
of the data. Never rely on memory for current facts.
If this request is clearly beyond what you should handle, do no work and reply with exactly one line:
ESCALATE: <agent-name> - <short reason>"""
    user = f"Agent City job #{job}. The request from the city's owner:\n\n<<<\n{request}\n>>>"
    return system, user


def run_agent(agent: dict, request: str, job: int, out_dir: str) -> dict:
    can_write = "Write" in agent["tools"]
    tools = list(agent["tools"])
    if "Bash" in tools:
        tools = [t for t in tools if t != "Bash"] + BASH_OK
    system, user = build_prompt(agent, request, job, out_dir, can_write)
    cmd = ["claude", "-p", user, "--model", agent["model"], "--max-turns", str(MAX_TURNS[agent["tier"]]),
           "--output-format", "json", "--append-system-prompt", system,
           "--allowedTools", ",".join(tools), "--permission-mode", "acceptEdits"]
    print(f"running {agent['name']} on {agent['model']} (max {MAX_TURNS[agent['tier']]} turns)")
    p = sh(cmd, check=False, timeout=60 * 40, cwd=ROOT)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        res = {"is_error": True, "result": (p.stdout + "\n" + p.stderr)[-3000:]}
    if res.get("is_error") or p.returncode:
        detail = f"exit {p.returncode}\nresult: {str(res.get('result'))[:1500]}\nstderr: {p.stderr[-1500:]}"
        print(detail, file=sys.stderr)
        (Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "city-error.txt").write_text(detail)
    res["_agent"], res["_model"], res["_tier"] = agent["name"], agent["model"], agent["tier"]
    return res


def cmd_run():
    job = int(os.environ["ISSUE_NUMBER"])
    out_dir = f"outputs/job-{job}"
    agents = all_agents()
    request, forced = parse_request()
    if forced and forced in agents:
        name, how = forced, "chosen by you"
    else:
        name, how = route(request, agents)
    agent = agents[name]

    for lbl, color in [("city-job", "4fd1ff"), ("status:working", "f7c948"), ("status:done", "3ddc84"),
                       ("status:failed", "ff5c5c"), (f"agent:{name}", "b98cff")]:
        gh("label", "create", lbl, "--color", color, "--force")
    gh("issue", "edit", str(job), "--add-label", f"city-job,status:working,agent:{name}",
       "--remove-label", "status:done,status:failed")
    gh("issue", "comment", str(job), "--body",
       f"🏗️ Routed to **{name}** ({agent['tier']} · {agent['model']}) via {how}. Working on it…")

    runs = [run_agent(agent, request, job, out_dir)]
    m = re.match(r"\s*ESCALATE:\s*([a-z]+)\s*[-–—:]?\s*(.*)", runs[-1].get("result") or "", re.I)
    if m and m.group(1).lower() in agents:
        nxt = agents[m.group(1).lower()]
        if nxt["name"] != agent["name"]:
            gh("issue", "comment", str(job), "--body",
               f"⬆️ **{agent['name']}** handed off to **{nxt['name']}** ({nxt['tier']} · {nxt['model']}): {m.group(2)}")
            gh("label", "create", f"agent:{nxt['name']}", "--color", "b98cff", "--force")
            gh("issue", "edit", str(job), "--add-label", f"agent:{nxt['name']}", "--remove-label", f"agent:{name}")
            runs.append(run_agent(nxt, request, job, out_dir))

    final = runs[-1]
    out = ROOT / out_dir
    out.mkdir(parents=True, exist_ok=True)
    readme = out / "README.md"
    text = (final.get("result") or "").strip()
    if not readme.exists() or readme.stat().st_size < 40:
        readme.write_text(f"# Job #{job}\n\n{text}\n")
    cost = sum(float(r.get("total_cost_usd") or 0) for r in runs)
    meta = {"job": job, "agent": final["_agent"], "model": final["_model"], "tier": final["_tier"],
            "route": how, "escalated_from": runs[0]["_agent"] if len(runs) > 1 else None,
            "turns": sum(int(r.get("num_turns") or 0) for r in runs), "cost_usd_estimate": round(cost, 4),
            "ok": not final.get("is_error"), "subtype": final.get("subtype"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "job.json").write_text(json.dumps(meta, indent=2))
    STATE.write_text(json.dumps({**meta, "summary": text[:3500], "out_dir": out_dir}))
    print(json.dumps(meta, indent=2))
    if final.get("is_error") and final.get("subtype") != "error_max_turns":
        sys.exit(1)


def cmd_finish():
    st = json.loads(STATE.read_text())
    repo, ref = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_REF_NAME", "main")
    link = f"https://github.com/{repo}/tree/{ref}/{st['out_dir']}"
    note = " (hit its turn limit; result may be partial; add the `run-again` label to retry)" \
        if st.get("subtype") == "error_max_turns" else ""
    body = (f"✅ **Done by {st['agent']}** · {st['tier']} · `{st['model']}` · {st['turns']} turns · "
            f"≈ ${st['cost_usd_estimate']:.2f}{note}\n\n📁 **Files:** {link}\n\n---\n\n{st['summary']}")
    gh("issue", "comment", str(st["job"]), "--body", body)
    gh("issue", "edit", str(st["job"]), "--add-label", "status:done", "--remove-label", "status:working,run-again")
    gh("issue", "close", str(st["job"]))


def cmd_fail():
    job = os.environ["ISSUE_NUMBER"]
    run = f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}"
    gh("label", "create", "status:failed", "--color", "ff5c5c", "--force")
    gh("issue", "edit", job, "--add-label", "status:failed", "--remove-label", "status:working")
    err_file = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "city-error.txt"
    err = err_file.read_text()[-2500:] if err_file.exists() else "(no details captured)"
    for secret in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        val = os.environ.get(secret)
        if val:
            err = err.replace(val, "***")
    gh("issue", "comment", job, "--body",
       f"❌ The job failed. Log: {run}\n\n<details><summary>Error details</summary>\n\n```\n{err}\n```\n</details>\n\n"
       f"Most common cause: the `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) secret is missing, mistyped or expired. "
       f"Add the `run-again` label to retry.")


if __name__ == "__main__":
    {"run": cmd_run, "finish": cmd_finish, "fail": cmd_fail}[sys.argv[1]]()
