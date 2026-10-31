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
| `.github/workflows/city-resume.yml` + `scripts/city_resume.py` | If a job stops because your Claude usage limit ran out, it is **paused** (label `status:paused`, progress saved on branch `checkpoint/job-N`). Every 30 minutes this checks (free, no Claude usage) and restarts it from where it left off once the limit has reset. |

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

## Modes

| Mode | How | What happens |
|---|---|---|
| 🛠 **Make** | Type a request, press Send | The cheapest fitting agent builds it into `outputs/job-N/`. Websites, games and apps come with a **▶ Open it** link. |
| 🔁 **Repeat** | Pick *Every day / weekday / week* and a time | Runs now, then on schedule in your time zone. A free hourly check (`city-schedule.yml`) starts it; stop it from **Jobs → Recurring**. |
| ✏️ **Change this** | Open a finished job, click *Change this* | The agent reads that job's files and makes an improved copy, so it doesn't start from scratch. |
| 🏗 **Upgrade city** | Switch to *Upgrade city* | Coder changes the city itself (new agents, buildings, features) and sends you a pull request. Nothing goes live until you click **Merge**. |

Upgrades can't edit `.github/` (GitHub blocks that). For the approval page to be created automatically, tick
**Settings → Actions → General → Allow GitHub Actions to create and approve pull requests**. Without it, the
job gives you a link to create it with one click.

## 🎰 Lucky Tower: the self-learning betting model

The slot-machine building is an NFL + NBA betting model (`bets/`) for DraftKings and Underdog. Click it, or open
the **Bets** tab, to see today's board: 🔥 best bets, 👍 leans, every game line, DK props, Underdog legs/entries and
hundreds of player projections, with search and filters.

- **Twice a day** (`bets-daily.yml`, about 11:20am and 5:50pm ET) it grades finished games, retunes itself,
  and builds a fresh board. This is plain Python, so it uses **no Claude usage**.
- **It learns every day:** every priced bet and projection is recorded and graded. It relearns how much to trust its
  model versus the market for each bet type, and corrects each stat's projections (too high or low, too
  confident or not enough). What it learned shows in the Bets tab and `bets/history/learning_log.json`.
- **It gets coached weekly:** every Monday, Quant reviews the results and proposes code improvements as a pull
  request you approve (a recurring job, which uses a little usage; stop it under Jobs → Recurring).
- Optional: add a free `ODDS_API_KEY` secret (the-odds-api.com) for DraftKings player props and Underdog lines.

Estimates, not guarantees. Gambling problem? Call 1-800-GAMBLER.

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
