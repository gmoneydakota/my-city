# Agent City

Agent City is a maker: people ask it to **build things** (apps, scripts, models,
documents) and agents in `.claude/agents/` do the work. Jobs usually run unattended
on GitHub Actions (`scripts/city_job.py`), but the same rules apply when you use
the agents interactively.

## Where things go
- Every job's deliverables go in `outputs/job-<n>/`, with a `README.md` that says
  what was made and exactly how to use it. Don't edit files outside that folder,
  except `watchlist.json` when asked to track a ticker.
- `outputs/signals/` is written only by `scripts/signals.py` (the free daily scan).
- Use fresh data for anything time-sensitive: `python3 scripts/market_data.py TICKER`
  for prices, WebSearch for news. State the date of the data.

## Spend usage like it's yours (it is)
Nine agents in three tiers:

- **Light (Haiku): `runner`, `scribe`**: quick answers, writing, rewrites.
- **Standard (Sonnet): `planner`, `tutor`, `scout`, `quant`**: plans,
  explanations, research, stock models.
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
- `scout` → `forge`: pass its findings straight over, don't re-research.

In unattended runs, an agent escalates by replying with one line:
`ESCALATE: <agent> - <reason>`. The runner allows one hop.

Don't escalate for its own sake. If the light answer is good enough, stop.
