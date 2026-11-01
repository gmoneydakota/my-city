---
title: Ship an app as a static page
tags: web, html, app, game, dashboard, github-pages
agents: coder, quant
learned_from: 9
related: add-city-building, budget-template
---
## When to use
Anything visual or interactive: a web app, game, dashboard, tracker or tool.

## How
1. Write one self-contained `outputs/job-N/index.html`. Libraries from a CDN are fine; no server, no build step.
2. Make it work on a phone: viewport meta tag, flexible layout, big touch targets.
3. Save the user's data in `localStorage` (prefix keys with the app name).
4. Data the page needs goes next to it as JSON, loaded with a relative `fetch()`; that works on GitHub Pages.
5. The README gives the link: `https://<owner>.github.io/<repo>/outputs/job-N/`.

## Gotchas
- GitHub Pages is static: no secrets and no server code in the page.
