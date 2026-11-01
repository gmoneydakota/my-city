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
| `agents/cad.md` | The 10th agent, **CAD**: designs working 3D models. The job runner loads agents from here too. |
| `cad/` | **CAD Studio**, the app behind the CAD tower: `index.html` (viewer/animator/exporter), `SCHEMA.md` (model format), `examples/`. |
| `scripts/cad_check.py` | Checks a CAD model for errors and physical nonsense (floating parts, not on the floor). No Claude usage. |
| `scripts/city_job.py` | The cloud job runner: routes, runs the agent on its tier, escalates once if asked, saves output. |
| `brain/` + `scripts/brain.py` | The **Second Brain**: skills the agents learned (`brain/skills/*.md`), the web page behind the brain building, and the free script that links skills, agents, tools and job history into `brain/brain.json`. |
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

## 🧊 CAD Tower: 3D models of anything

Click the **CAD** tower (the one with the spinning hologram) and the city flies you into **CAD Studio** (`cad/`).

- Describe anything ("a treasure chest whose lid opens", "a 3D-printable phone stand") and press **Design it**. The
  **CAD** agent (Sonnet) designs it at real size in millimetres, adds the hinges, wheels, gears and sliders that make
  it work, writes "how it works" steps, and runs `scripts/cad_check.py` so no part floats. That takes about 3–10
  minutes, and the studio opens the model by itself when it's ready.
- In the studio: **▶ Play** to watch it work, drag the joint sliders, use **exploded view** and **X-ray**, click any part to see
  what it's for, then **⬇ STL** (3D printing), **⬇ GLB** (Blender, AR, game engines) or **⬇ JSON**.
- **✏️ Change this model** sends a follow-up that edits the earlier design instead of starting over.
- Three working examples (desk lamp, gear train, rover) are there even before you connect a repo.
- Requests in the normal Make box that mention "3D model", "3D print", "CAD" or "STL" go to the CAD agent too.

The CAD agent lives in `agents/cad.md`, not `.claude/agents/`, because the upgrade job that built it wasn't allowed to
write inside `.claude/`. The job runner reads both folders. To also use it as a Claude Code subagent on your own
computer, copy it with `cp agents/cad.md .claude/agents/`. That's optional, and the copy in `.claude/agents/` wins.

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

## 🧠 Second Brain: what the city has learned

The glowing pink brain just past the Quant tower is the city's memory. Click it and you fly into `brain/`: a live web of
every **skill** (hexagons) the agents have learned, the **agents** that use them, the **tools** (scripts, CAD Studio,
the betting model) and every past **job** (the history). Drag, zoom, search, and click a node to read it.

- **Agents use it:** every job's prompt lists the skills, and the agent reads the ones that match before it starts.
- **Agents grow it:** when an agent works out a reusable method, it saves it to `brain/skills/<slug>.md`. After every
  job the runner rebuilds the web (`scripts/brain.py`, free, no Claude usage), so new skills and jobs appear by themselves.
- **You can teach it:** type a lesson in the brain page (“when I ask for a workout plan, always add warm-ups”) and
  Scribe (Haiku, the cheapest tier) writes it in as a skill.
- **It dreams on its own:** every Sunday at 10:00 ET, Scribe reviews the week's jobs and adds or improves 1–2 skills,
  sometimes inventing a technique from tools it already has. Stop it under **Jobs → Recurring** like any repeat job.
- Skills are plain Markdown, so you can edit or delete them on GitHub too. `python3 scripts/brain.py --check`
  lists broken links between skills.

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
