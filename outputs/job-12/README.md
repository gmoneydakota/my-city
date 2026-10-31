# Lean Reader: an MCP connector that saves Claude usage on web reading

**Job #12, built 31 October 2026.** You asked for a connector that uses your Claude usage as efficiently as possible without taking away any of Claude's abilities.

## The idea

Much of a Claude conversation's usage goes to **reading**. When Claude reads a whole web page or API response, all of it lands in the conversation: navigation menus, footers, reference lists, and long JSON fields nobody asked for. That text is then re-read on every later turn.

Lean Reader lets Claude read **like a person skimming**. It looks at the table of contents first, then reads only the parts it needs. Nothing is hidden. Every word of every page is still reachable through paging, so Claude can still read everything. It just doesn't receive everything at once by default.

Real numbers from the test run (31 Oct 2026, Wikipedia's "Model Context Protocol" article):

| How Claude reads it | Approx. tokens |
|---|---|
| Raw HTML of the page | ~66,300 |
| Whole page as clean text (`page_read`, all sections) | ~4,800 |
| Outline only (`page_outline`) | ~120 |
| Outline + the one section needed (`page_read sections:[1]`) | ~420 |
| Just the 2 best paragraphs answering a question (`page_search`) | ~280 |

The JSON side is similar. A GitHub API repo response has 86 top-level keys and well over 1,000 tokens of JSON. `json_pick` with four paths returned about 50 tokens.

## The 5 tools (all read-only, public web data only)

| Tool | What it does |
|---|---|
| `page_outline` | Title, description, and numbered sections with a token estimate for each. Use it first. |
| `page_read` | Clean text of chosen sections (or the whole page), paged by `offset` / `max_chars`. |
| `page_search` | Paragraphs that match keywords, labelled with their section, plus optional surrounding context. |
| `page_links` | De-duplicated absolute links, filterable by text or URL and optionally limited to the same site. Useful for navigating. |
| `json_pick` | With no paths: a compact **shape map** of a JSON API (every key path, its type, and an example value). With paths such as `data.items[*].name` or `results[0]`: only those values, with long arrays and strings trimmed. |

Other usage-saving details:
- Pages are **cached for 10 minutes**, so an outline followed by a read or search downloads the page only once.
- The server sends Claude **instructions** describing the workflow: outline first, then read or search.
- Tool definitions cost about **1,200 tokens** while the connector is turned on (measured by the test). One avoided raw page more than pays for that, but turn the connector off in chats that won't involve reading web pages or APIs.

What it does **not** do: it can't reduce Claude's own thinking or writing, and it doesn't replace Claude's built-in web search. Use web search to *find* pages and Lean Reader to *read* them cheaply.

## Files

```
outputs/job-12/
├── src/server.ts      the MCP server (TypeScript, @modelcontextprotocol/sdk, Streamable HTTP)
├── test/smoke.mjs     end-to-end test: every tool, plus auth and private-network blocking
├── package.json       dependencies and scripts
├── tsconfig.json
├── .env.example       settings, including the CONNECTOR_SECRET
└── .gitignore
```

## Run it locally

You need Node.js 20 or newer.

```bash
cd outputs/job-12
npm install
cp .env.example .env            # optional, for reference. The server reads real environment variables
npm run build
CONNECTOR_SECRET=pick-a-long-random-string npm start
# → lean-reader MCP listening on http://localhost:8787/mcp/<CONNECTOR_SECRET>
```

Run the automated test. It builds the server, starts it, calls all 5 tools against live sites, and checks the security rules:

```bash
npm test          # should end with: ALL CHECKS PASSED
```

### Test interactively with the MCP Inspector

1. Start the server as shown above.
2. In another terminal, run `npx @modelcontextprotocol/inspector`. It opens in your browser.
3. Set **Transport** to *Streamable HTTP* and **URL** to `http://localhost:8787/mcp/pick-a-long-random-string`, then click **Connect**.
4. Open **Tools → List Tools**, choose `page_outline`, enter a URL such as `https://en.wikipedia.org/wiki/Model_Context_Protocol`, and click **Run**.

## Deploy it with a public HTTPS address (Render, free tier)

Claude can only connect to a server that is reachable over HTTPS on the internet. Render is one of the simplest options, but any Node host works (Railway, Fly.io, a VPS behind Caddy, and so on).

1. Push this repo to GitHub (it's already there).
2. On <https://render.com>, choose **New → Web Service** and pick this repo.
3. Set **Root Directory** to `outputs/job-12`, the **Build Command** to `npm install && npm run build`, and the **Start Command** to `npm start`.
4. Under **Environment**, add `CONNECTOR_SECRET` with a long random value. You can generate one with:
   `node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"`
5. Deploy. Visiting `https://<your-app>.onrender.com/` should show "lean-reader MCP server is running".

Your connector URL is: `https://<your-app>.onrender.com/mcp/<CONNECTOR_SECRET>`

(Free Render services go to sleep when idle, so the first call after a while can take about 30 seconds. A paid instance or another host avoids this.)

## Add it to Claude as a custom connector

1. In Claude (web or desktop), go to **Settings → Connectors → Add custom connector**. On Team or Enterprise plans, an owner adds it under the organisation's connector settings.
2. Name: `Lean Reader`. URL: `https://<your-app>.onrender.com/mcp/<CONNECTOR_SECRET>`. Leave the OAuth fields empty.
3. Save, then enable it in a chat from the tools/connectors menu.
4. Try: *"Use Lean Reader to outline https://en.wikipedia.org/wiki/Model_Context_Protocol, then tell me just what the Security section says."*

For Claude Code: `claude mcp add --transport http lean-reader https://<your-app>.onrender.com/mcp/<CONNECTOR_SECRET>`

Plan availability and menu names change over time. If a menu doesn't match, check Anthropic's help page on custom connectors.

## Security (read this)

- **Auth gap, stated plainly:** Claude's custom-connector form uses OAuth or no auth; it can't send a custom API key header. So this server is protected by a **secret in the URL path**. Anyone who learns the full URL can use your server. Keep the URL private. If it leaks, change `CONNECTOR_SECRET` and update the connector. With `CONNECTOR_SECRET` unset, the server is **completely open** and logs a warning. Only do that on your own machine. The server also accepts `Authorization: Bearer <secret>` at `/mcp` for clients that can send headers. Adding full OAuth would be the next step if you need real per-user auth.
- **What an attacker could do with the URL:** only fetch *public* web pages through your server. That uses your host's bandwidth and could make your server's IP look like the one fetching those pages. There is no access to your data, your Claude account, or anything private.
- **Private-network blocking:** every connection, including each redirect, is checked against private, loopback, link-local, cloud-metadata (169.254.169.254), CGNAT, and reserved IP ranges, including IPv4-mapped IPv6 forms. The check runs at DNS-resolution time, so DNS-rebinding tricks fail too. Only ports 80, 443, 8080, and 8443 are allowed, and URLs containing credentials are rejected.
- **Limits:** 10-second fetch timeout, a 3 MB download cap (pages beyond that are cut off and flagged), at most 5 redirects, 60 requests per minute per IP, and every tool input validated with zod. The server never runs shell commands or `eval`.
- No secrets are hard-coded. All settings come from environment variables (see `.env.example`).

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `CONNECTOR_SECRET` | *(empty: open!)* | Secret path segment / bearer token |
| `PORT` | 8787 | Port to listen on |
| `CACHE_TTL_SECONDS` | 600 | How long fetched pages stay cached |
| `FETCH_TIMEOUT_MS` | 10000 | Outbound request timeout |
| `MAX_DOWNLOAD_BYTES` | 3000000 | Largest page downloaded |
| `RATE_LIMIT_PER_MINUTE` | 60 | Requests per minute per client IP |

## Assumptions made (unattended job)

- "Use my usage efficiently" was read as **cutting the tokens Claude spends reading external content**, which is the main thing a connector can control. A connector can't change how Claude itself thinks or writes.
- "Doesn't take away from Claude's powers" was read as **nothing is made unreachable**. Every tool can page through the full content, and Claude decides how much to read.
- Public web pages and JSON APIs only, read-only, with no logins to third-party sites.
- Written in TypeScript with the official MCP SDK (v1.32), using stateless Streamable HTTP. Render is suggested as the HTTPS host.
- Nothing visual was requested, so there is no `index.html`. This job doesn't change the city itself.
