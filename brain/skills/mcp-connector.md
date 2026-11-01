---
title: Build an MCP connector
tags: mcp, connector, server, api, typescript
agents: scout, forge
learned_from: 12
related: escalate-one-hop
---
## When to use
Connecting Claude to an app or data source.

## How
1. Scout first checks that no good server already exists; forge builds only when none does, using scout's findings as they are.
2. Keep the tools few and sharp, read-only unless asked, each with a clear description (job 12 had 5).
3. Save usage: return an outline and the relevant slice first, with paging to reach everything (job 12 cut a page from ~66k tokens to ~420).
4. Ship `package.json`, `.env.example`, tests, and a README with measured numbers and deploy steps.
