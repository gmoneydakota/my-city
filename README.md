# 🏙️ Agent City

A glowing 3D city of AI agents that **build things for you**: apps, scripts, games,
documents, and stock models with buy signals. You type a request into the city, and it
runs on GitHub's servers, so **your computer can be off**. Come back later and the
result is waiting in the city (and in your repo).

```
 you (phone or laptop) ──► 3D city page ──► GitHub issue "[city] …"
                                               │
                          GitHub Actions ◄─────┘   (your computer can be off)
                               │
             free keyword router (or 1 tiny Haiku call if unclear)
                               │
        Light: Haiku ─► Standard: Sonnet ─► Heavy: Opus   (escalates only if needed)
                               │
          outputs/job-N/  +  comment on the issue  +  tower lights up in the city
```

## What's in here

| Path | What it does |
|---|---|
| `index.html` | The 3D city (Three.js). Towers are agents. Orbs fly to a tower when it's working, and beams light up while it builds. Tabs: **Make**, **Jobs**, **Market**. |
| `.claude/agents/*.md` | The 9 agents: your original 8 plus **quant** for stock models. |
| `scripts/city_job.py` | The cloud job runner: routes, runs the agent on its tier, escalates once if asked, saves output. |
| `scripts/market_data.py` | Fresh daily prices, no API key (Yahoo Finance, falling back to Stooq). |
| `scripts/signals.py` | Daily buy/hold/avoid signals with reasons and an honest backtest. **Uses zero Claude usage.** |
| `watchlist.json` | Tickers the daily scan covers. Edit freely. |
| `.github/workflows/city-job.yml` | Runs a job whenever you send one from the city. |
| `.github/workflows/market-signals.yml` | Free weekday scan after the US market close. |

## Setup (about 10 minutes, once)

1. **Make a GitHub repo** and push this folder to it (instructions below). Public is
   easiest because free GitHub Pages needs a public repo. Only *your* requests ever
   run: issues opened by anyone else are ignored, so strangers can't spend your usage.
2. **Give it access to Claude.** Pick one:
   - **Claude Pro/Max plan:** on any computer with Claude Code, run `claude setup-token`,
     copy the token, then in the repo go to **Settings → Secrets and variables → Actions →
     New repository secret** and add it as `CLAUDE_CODE_OAUTH_TOKEN`.
   - **API key (pay per use):** add it as `ANTHROPIC_API_KEY` instead.
3. **Turn on the website:** **Settings → Pages → Deploy from a branch → `main` / root**.
   Your city appears at `https://<you>.github.io/<repo>/` within a minute or two.
   Bookmark it on your phone.
4. **Run the first market scan:** **Actions → market-signals → Run workflow**. After that
   it runs by itself every weekday.
5. *(Optional)* In the city, open ⚙ and paste a fine-grained GitHub token with **Issues**
   and **Contents** read/write access for this repo. Then **Send** submits jobs instantly.
   Without the token, Send opens a pre-filled GitHub page and you click *Create*.
   The token is saved only in your browser.

```bash
cd agent-city
git init -b main && git add -A && git commit -m "Agent City"
```

```bash
gh repo create agent-city --public --source . --push
```

## Using it

- Type what you want built, or tap an example chip. Under the box, the city shows
  which agent will take the job and which model it will use, before you send it.
- Pick an agent yourself from the dropdown if you want to control the cost.
- Click any tower to see that agent's jobs. Click a job to read what was built. Every
  file is in `outputs/job-N/` in your repo.
- To retry a failed job, add the `run-again` label to its issue.

## How it saves usage

1. **No model for mechanical work.** Market data and signals are plain Python on a
   schedule, so they cost nothing.
2. **Free routing.** Keyword rules pick the agent. A single Haiku call is used only when
   a request is ambiguous.
3. **No manager model.** The chosen agent runs directly on its own tier instead of an
   Opus orchestrator sitting on top of it.
4. **Escalation, not over-provisioning.** Light and standard agents reply
   `ESCALATE: <agent>` when a job is beyond them, and only then does a heavier model run
   (one hop max).
5. **Hard caps.** Turn limits of 12, 35, and 70 by tier, and a 50-minute job timeout.
   Each job reports its turns and estimated cost.

## About the stock signals

`signals.py` scores each ticker from trend (50/200-day averages), 3-month momentum vs SPY,
MACD, RSI, and "pullback to the 50-day in an uptrend" setups. It labels each one
**BUY ZONE / WATCH / HOLD / AVOID**, lists the reasons, suggests a stop, and backtests the
same rule on that ticker's own history so you can see how often it actually worked.
For a deeper model on one stock (news, earnings, custom rules), ask **Quant** in the city.

This is an educational tool, not financial advice. No signal can tell you for certain
when to buy, so treat it as one input among several.

## Security notes

- Only issues opened by the repo owner trigger jobs.
- Agents get only the tools in their `.md` file. Shell access is limited to Python,
  Node, and package managers, and they're told to write only inside their job folder.
- Your Claude token lives in GitHub Secrets. Your optional GitHub token lives only in your
  browser's local storage.
