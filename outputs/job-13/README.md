# Job 13 · City upgrade: the Second Brain building

A new landmark: a glowing, wrinkled **brain** with synapses firing inside it. Click it and you fly into the
**Second Brain**, a live web of everything the city knows: the skills its agents learned, the agents and
tools that use them, and every past job. It isn't only a picture. The agents read the brain before each job
and write new skills into it afterwards, so the city learns as it goes.

## What you'll see after approving (Merge)

**In the city:** past the Quant tower, on a pink-lit plinth, a two-hemisphere brain with a brain stem,
a cerebellum and a pink wireframe skin. Hundreds of synapse sparks twinkle inside it, linked by flickering nerves, and the
whole thing slowly "breathes". One small crystal orbits it for every skill it knows (up to 30). The label says
**🧠 Second Brain**, and its badge shows e.g. `11 skills · 10 memories`. Click the brain or its label:
the camera swoops in, the screen fades, and the brain page opens.

**The brain page (`brain/`):**
- A brain-shaped neural web (two lobes) of **skills** (pink hexagons), **agents** (big glowing dots, coloured by
  Haiku/Sonnet/Opus tier, sized by how many jobs they've done), **tools** (yellow squares), **jobs = history** (green dots) and
  **topics** (grey). Sparks travel along the links. Drag to pan, scroll or pinch to zoom, drag nodes around.
- Hover a node to light up its connections. Click it to read it: a skill's full how-to, an agent's prompt, a job's
  README, plus links to the file on GitHub, **▶ Open it** for job pages and **🧊 CAD Studio** for models.
- A search box over everything, a **library** list of all skills, the latest memories (jobs), and a legend that shows or hides each kind of node.
- **✨ Teach it something:** type a lesson and press *Add to the brain*. That sends a normal city job to
  **Scribe** (Haiku, the cheapest tier), which writes it in as a new skill (or improves an existing one).
- **💭 Let it dream:** runs the same "dream" as the weekly one, right away.
- Links like `brain/#skill:add-city-building` open straight to one node.

## How it learns by itself

1. **Before every job** the runner adds the brain's skill list to the agent's prompt and tells it to read the
   skills that match its job. Only the skill list goes in (about 500 tokens), to keep usage low.
2. **After every job**, an agent that worked out a reusable method saves it as `brain/skills/<slug>.md`
   (make-mode jobs may now write there; agents that can't write files leave a "Skill learned:" note instead).
3. **After the job is saved**, `scripts/brain.py` (free, no Claude usage) rebuilds `brain/brain.json` and
   `brain/INDEX.md` from the skills, agents, scripts and `outputs/`, so new jobs and skills show up in the web by themselves.
4. **Every Sunday at 10:00 ET**, the new recurring job **"Brain dream"** (Scribe, Haiku) reviews the week's jobs and
   any "Skill learned:" notes, then adds or improves 1-2 skills. It may invent a new technique from tools the city already has.
   It shows under **Jobs → Recurring**, and you can stop it there.

It starts with **11 skills**, taken from what the city has actually done: adding a building (jobs 3, 9, this one),
static app pages (9), CAD models (7, 8), stock signal models, the betting-model learning loop (2, 6), MCP connectors (12),
quick answers (1), budget templates (4), cheapest-agent routing, surviving usage limits, and "how to teach the brain a skill".

## Files

| File | Change |
|---|---|
| `index.html` | New **Second Brain** building at (0, 0, 82): geometry, synapses, orbiting skill crystals, label + badge, click → `brain/`, a pink boulevard to it, a gap in the filler buildings around it, and `refreshBrain()` to load the skill count (every 15 min, like Bets). |
| `brain/index.html` | **New.** The brain page (self-contained canvas force-graph, no build step, works on a phone). |
| `brain/skills/*.md` | **New.** 11 seed skills. |
| `brain/brain.json`, `brain/INDEX.md` | **New, generated** by `scripts/brain.py`. Don't edit by hand. |
| `scripts/brain.py` | **New.** Builds the web. `--check` reports broken skill links or unknown agents. |
| `scripts/city_job.py` | The brain goes into every agent's prompt. Make jobs may write `brain/skills/`. After a make job is pushed, the index is rebuilt in its own commit. That avoids merge conflicts when jobs run at the same time: the index is generated from the files, so a push race just rebuilds it. Upgrade PRs leave the generated files alone for the same reason. The upgrade map now lists `brain/`. |
| `schedules.json` | New recurring job `9002` "Brain dream" (weekly, Sunday 10:00 America/New_York, Scribe). |
| `sw.js` | Caches `brain/` for offline use; cache bumped to v3. |
| `CLAUDE.md`, `README.md` | Document the brain and the new `brain/skills/` exception. |

No `.github/` changes were needed.

## Checks run
- `node --check` on the city's module script and on the brain page script: both parse.
- Node smoke test of the brain page against the real `brain.json` with a stubbed DOM: the web renders, the deep link
  opens a skill, and pan/zoom/click work without errors.
- Node smoke test of the new building code against real three.js 0.160: no NaN vertices, 14 orbiters after
  `setBrainSkills(14)`, and a click opens `brain/`.
- A simulated `save` against a throwaway git origin: the job commit holds only the job's files and the new skill,
  then a separate "Brain: refresh index" commit adds the new skill and job to the index.
- `python3 -m py_compile` on all changed Python. `python3 scripts/brain.py --check`: 11 skills, 0 problems.
- I couldn't take a real browser screenshot (headless Chrome isn't allowed on this runner), so how it looks hasn't been checked by eye.

## Assumptions
- "Skills and history" means the agents' how-to knowledge (skills), the agents and tools themselves, and every
  past job. All of these appear in the web.
- Teaching and dreaming use **Scribe** (Haiku), because writing a skill note is mostly writing and Scribe can save files.
  Teach requests are sent with `Mode: make`, so they never turn into city upgrades.
- The weekly dream runs Sunday 10:00 ET, on a different day from the Monday 09:00 ET betting coach, so the two
  never compete. If this is merged on a Sunday after 10:00 ET, the first dream runs that same day.
- Skill notes must never contain secrets. The learn-a-skill skill says so.
- Until this PR is merged, the old runner code is live, so this job's own entry in the brain is filled in by the next job's index rebuild.
