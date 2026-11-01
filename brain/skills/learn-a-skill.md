---
title: Teach the brain a new skill
tags: brain, memory, learning, skills, meta
agents: runner, scribe, planner, tutor, scout, quant, cad, analyst, coder, forge
learned_from: 13
related: add-city-building
---
## When to use
At the end of any job where you worked out a reusable way of doing something that isn't in `brain/INDEX.md` yet, or found a better way than an existing skill.

## How
1. Pick a short kebab-case slug, e.g. `scrape-a-table`. If a skill about the same thing exists, improve that file instead of adding a twin.
2. Write `brain/skills/<slug>.md`:
   ```
   ---
   title: Scrape a table from a web page
   tags: web, data, scraping
   agents: coder, quant
   learned_from: 14
   related: static-job-page
   ---
   ## When to use
   ## How
   1. ...
   ## Gotchas
   ```
3. Write the method, not the job's answer: steps a future agent can follow, the commands that worked, the traps you hit.
4. `related` links skills into the web. Use slugs of skills that really exist.
5. Optional: `python3 scripts/brain.py` refreshes the index (the runner does it after every job anyway).

## Gotchas
- One skill per file, under ~60 lines. Never put secrets, tokens or personal data in a skill.
