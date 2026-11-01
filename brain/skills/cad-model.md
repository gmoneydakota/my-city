---
title: Make a working 3D model for CAD Studio
tags: cad, 3d, model.json, mechanism, stl
agents: cad
learned_from: 7, 8
related: learn-a-skill
---
## When to use
"Make me a 3D model of ...", printable parts, mechanisms with moving joints.

## How
1. Read `cad/SCHEMA.md` and one example in `cad/examples/` (lamp = hinge, gearbox = gears, rover = wheels and a lid).
2. Units are mm, Y is up, the floor is y = 0. Every `pos`, `pivot` and `axis` is in world coordinates in the rest pose.
3. For many repeated parts, write a small generator script (job 8 used `gen_model.py`) instead of typing coordinates by hand.
4. Run `python3 scripts/cad_check.py outputs/job-N/model.json`. Fix every error and the warnings that matter (floating parts, pivots far from their part).
5. Fill `how_it_works` and `assumptions` so the owner understands the mechanism.

## Gotchas
- A remix (job 8 replaced job 7's door) copies the old model first, then changes it.
