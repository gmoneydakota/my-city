---
title: Build an MCP connector
tags: mcp, connector, server, api, typescript, security
agents: scout, forge
learned_from: 12
related: escalate-one-hop, secure-public-fetch, learn-a-skill
---
## When to use
Connecting Claude to an app, API or data source through a custom connector (Streamable HTTP server).

## How
1. Scout first checks that no good server already exists. Forge builds only when none does, using scout's findings as they are.
2. Keep the tools few and sharp, read-only unless asked, each with a clear description and zod-validated inputs (job 12 had 5).
3. Save usage: return an outline and the relevant slice first, with paging to reach everything. Job 12 cut a Wikipedia article from ~66,300 tokens (raw HTML) to ~4,800 (clean text) and ~420 (one section). Put the workflow in the server's instructions field so Claude uses it.
4. Measure the numbers before you claim them: count tokens for raw vs. sliced output and put the table in the README.
5. Protect the endpoint. Claude's custom-connector form only offers OAuth or no auth, so use an unguessable secret path segment (`/mcp/<SECRET>`), compare it with `timingSafeEqual` on hashes, also accept `Authorization: Bearer`, and rate-limit per IP. With no secret set, log a loud warning at startup (job 12 started open and warned; say so in the README). Any fetch of user-given URLs follows `secure-public-fetch`.
6. Ship `package.json`, `.env.example` (no real secrets), an end-to-end smoke test that calls every tool, and a README with local run, MCP Inspector steps, deploy steps and the `claude mcp add --transport http` line.

## Gotchas
- Tool definitions cost tokens on every turn the connector is on (job 12 measured ~1,200). Tell the owner to switch it off in chats that don't read the web or APIs.
- Free hosts like Render sleep when idle; the first call can take ~30 s. Say so in the README.
- Connector menus and plan rules change. Mark them "as of the job date" and point to the vendor's help page.
- Never return raw HTML or whole API responses by default; a shape map (`json_pick` with no paths) beats dumping 86 top-level keys.
