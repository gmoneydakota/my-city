---
title: Add a building to the city
tags: city, three.js, upgrade, index.html
agents: coder
learned_from: 3, 9, 13
related: static-job-page, learn-a-skill
---
## When to use
The owner wants something to appear IN the 3D city: a tower, landmark, building, or a change to how the city looks.

## How
1. This must be an **upgrade** job (a pull request). Make-mode jobs cannot touch `index.html`; reply `ESCALATE: coder - ...` instead of handing over a patch (job 9 made a patch nobody applied).
2. Pick a free spot. Towers sit on a ring of radius 40, Lucky Tower at (40, -64), Products at (-40, -64), the Brain at (0, 82). Add the new spot to the filler-city exclusion test in `buildFiller()` so houses don't grow through it.
3. Build it as a `THREE.Group`, reuse `edgeMesh()` / `windowTexture()` / `glowLine()` so it matches the neon style, and give its meshes a `userData` flag and push them into `pickables`.
4. Add a CSS2D `.tag` label and handle the flag in the `pointerup` click handler.
5. If it opens a page, give the page its own folder (`cad/`, `brain/`) or use an `outputs/job-N/` page, and use the warp fade (`enterApp`) for the transition.
6. Animate it in its own `animateX(t, dt)` called from `animate()`.
7. Check the module parses: extract the `<script type="module">` and run `node --check`.

## Gotchas
- `g.lookAt(0,0,0)` turns the building's front toward the city centre.
- Keep geometry light; the city already draws ~1,400 filler buildings.
