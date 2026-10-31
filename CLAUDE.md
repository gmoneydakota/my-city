# Agent City

Agent City is a maker: people ask it to **build things** (apps, scripts, models,
documents) and agents in `.claude/agents/` do the work. Jobs usually run unattended
on GitHub Actions (`scripts/city_job.py`), but the same rules apply when you use
the agents interactively.

## Where things go
- Every job's deliverables go in `outputs/job-<n>/`, with a `README.md` that says
  what was made and exactly how to use it. Don't edit files outside that folder,
  except `watchlist.json` when asked to track a ticker.
- **Anything that must appear IN the city (a building, tower, landmark, or a change to how the city looks or
  behaves) means editing `index.html`, which only an upgrade job may do.** The runner now switches such requests to
  upgrade mode by itself. If a make-mode job ever finds it needs to change the city, don't hand over a patch: reply
  `ESCALATE: coder - this changes the city itself, it needs an upgrade (pull request)`. A finished page from a normal job
  (like `outputs/job-9/`) is fine, but the building that opens it must be added in `index.html` in the same job.
- `outputs/signals/` is written only by `scripts/signals.py` (the free daily scan).
- Use fresh data for anything time-sensitive: `python3 scripts/market_data.py TICKER`
  for prices, WebSearch for news. State the date of the data.

## Spend usage like it's yours (it is)
Ten agents in three tiers (`cad` lives in `agents/cad.md`; the job runner reads both folders):

- **Light (Haiku): `runner`, `scribe`**: quick answers, writing, rewrites.
- **Standard (Sonnet): `planner`, `tutor`, `scout`, `quant`, `cad`**: plans,
  explanations, research, stock models, working 3D models (`model.json` for CAD Studio,
  checked with `python3 scripts/cad_check.py`).
- **Heavy (Opus): `analyst`, `coder`, `forge`**: real implementation, deep
  analysis, MCP servers.

**Default to the lightest agent that could plausibly do the job.** Anything that
doesn't need a model at all (fetching prices, computing indicators, reformatting
data) should be a script, not an agent call.

**Escalate only when the current tier falls short.** Say in one line why, then hand off:
- `runner`/`scribe` → `planner` (needs a plan) or `tutor` (needs an explanation).
- `planner`/`tutor`/`scout` → `coder`, `analyst`, or `forge` when it needs building,
  rigorous multi-angle analysis, or a working server.
- `quant` → `coder` only when the request is a large application, not a model.
- `cad` → `coder` only when the request isn't really a 3D object.
- `scout` → `forge`: pass its findings straight over, don't re-research.

In unattended runs, an agent escalates by replying with one line:
`ESCALATE: <agent> - <reason>`. The runner allows one hop.

Don't escalate for its own sake. If the light answer is good enough, stop.
