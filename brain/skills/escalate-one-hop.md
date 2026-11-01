---
title: Pick the cheapest agent, escalate once
tags: routing, cost, escalate, tiers
agents: runner, scribe, planner, tutor, scout, quant, cad, analyst, coder, forge
learned_from:
related: pause-and-resume, quick-answer
---
## How
1. Light (Haiku): runner, scribe. Standard (Sonnet): planner, tutor, scout, quant, cad. Heavy (Opus): analyst, coder, forge.
2. If a request is beyond you, do no work and reply with one line: `ESCALATE: <agent> - <reason>`. The runner allows one hop.
3. Anything that needs no model (prices, indicators, reformatting) should be a script, not an agent call.
