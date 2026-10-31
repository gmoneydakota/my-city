/**
 * Lean Reader MCP server
 * ----------------------
 * Gives Claude a "progressive disclosure" way to read the web: look at a page's
 * outline first (a few hundred tokens), then pull only the sections, search hits,
 * links, or JSON fields it actually needs. Nothing is hidden from Claude - every
 * byte of a page is still reachable via paging - it just isn't dumped into the
 * context window by default.
 *
 * Tools (all read-only, public data only):
 *   page_outline  - title, description, numbered section list with sizes
 *   page_read     - read chosen sections, paginated by characters
 *   page_search   - keyword search inside a page, returns matching paragraphs
 *   page_links    - filtered list of links on a page
 *   json_pick     - shape summary of a JSON API, or only the fields you name
 */
import express, { type Request, type Response, type NextFunction } from "express";
import { createHash, timingSafeEqual } from "node:crypto";
import dns from "node:dns";
import net from "node:net";
import * as cheerio from "cheerio";
import { Agent, fetch } from "undici";
import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

// ---------------------------------------------------------------- config ---
function intEnv(name: string, def: number, min: number, max: number): number {
  const raw = process.env[name];
  const n = raw === undefined || raw === "" ? def : Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return def;
  return Math.min(max, Math.max(min, n));
}
const PORT = intEnv("PORT", 8787, 1, 65535);
const SECRET = (process.env.CONNECTOR_SECRET ?? "").trim();
const CACHE_TTL_MS = intEnv("CACHE_TTL_SECONDS", 600, 0, 86400) * 1000;
const FETCH_TIMEOUT_MS = intEnv("FETCH_TIMEOUT_MS", 10000, 1000, 60000);
const MAX_BYTES = intEnv("MAX_DOWNLOAD_BYTES", 3_000_000, 10_000, 20_000_000);
const RATE_LIMIT = intEnv("RATE_LIMIT_PER_MINUTE", 60, 1, 10000);
const MAX_REDIRECTS = 5;
const CACHE_MAX_ENTRIES = 50;
const ALLOWED_PORTS = new Set(["", "80", "443", "8080", "8443"]);
const USER_AGENT = "LeanReaderMCP/1.0 (+https://github.com/gmoneydakota/my-city)";

// ------------------------------------------------------ SSRF protection ---
// Block loopback, private, link-local, CGNAT, multicast, reserved, and
// IPv4-mapped / NAT64 IPv6 ranges so the server can't be used to reach
// internal networks or cloud metadata endpoints (169.254.169.254).
const blocked = new net.BlockList();
for (const [a, p] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10], ["127.0.0.0", 8],
  ["169.254.0.0", 16], ["172.16.0.0", 12], ["192.0.0.0", 24], ["192.0.2.0", 24],
  ["192.168.0.0", 16], ["198.18.0.0", 15], ["198.51.100.0", 24], ["203.0.113.0", 24],
  ["224.0.0.0", 4], ["240.0.0.0", 4],
] as const) blocked.addSubnet(a, p, "ipv4");
for (const [a, p] of [
  // NOTE: don't add ::ffff:0:0/96 here - Node's BlockList treats it as matching
  // every IPv4 address. IPv4-mapped IPv6 is handled in isBlockedIp instead.
  ["::", 128], ["::1", 128], ["64:ff9b::", 96], ["100::", 64],
  ["2001:db8::", 32], ["fc00::", 7], ["fe80::", 10], ["fec0::", 10], ["ff00::", 8],
] as const) blocked.addSubnet(a, p, "ipv6");

function isBlockedIp(ip: string): boolean {
  const fam = net.isIP(ip);
  if (fam === 4) return blocked.check(ip, "ipv4");
  if (fam === 6) {
    const low = ip.toLowerCase();
    // IPv4-mapped (::ffff:a.b.c.d or ::ffff:abcd:ef01): judge by the embedded IPv4.
    const m = /^(?:0{0,4}:){0,5}:?ffff:(.+)$/.exec(low);
    if (m) {
      if (net.isIP(m[1]) === 4) return isBlockedIp(m[1]);
      const hex = /^([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(m[1]);
      if (!hex) return true;
      const hi = parseInt(hex[1], 16), lo = parseInt(hex[2], 16);
      return isBlockedIp(`${hi >> 8}.${hi & 255}.${lo >> 8}.${lo & 255}`);
    }
    return blocked.check(ip, "ipv6");
  }
  return true;
}

// Every outbound connection resolves DNS through this check, so redirects and
// DNS-rebinding tricks can't sneak a private address past us.
const safeAgent = new Agent({
  connect: {
    lookup(hostname: string, options: any, cb: any) {
      dns.lookup(hostname, { all: true }, (err, addrs) => {
        if (err) return cb(err);
        const ok = addrs.filter((a) => !isBlockedIp(a.address));
        if (ok.length === 0 || ok.length !== addrs.length) {
          return cb(new Error(`Refusing to connect to non-public address for ${hostname}`));
        }
        if (options?.all) return cb(null, ok);
        cb(null, ok[0].address, ok[0].family);
      });
    },
  },
});

function validateUrl(raw: string): URL {
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    throw new Error("Not a valid URL.");
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") throw new Error("Only http and https URLs are allowed.");
  if (u.username || u.password) throw new Error("URLs with embedded credentials are not allowed.");
  if (!ALLOWED_PORTS.has(u.port)) throw new Error("Only ports 80, 443, 8080 and 8443 are allowed.");
  const host = u.hostname.replace(/^\[|\]$/g, "");
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".internal") || host.endsWith(".local")) {
    throw new Error("Local/internal hostnames are not allowed.");
  }
  if (net.isIP(host) && isBlockedIp(host)) throw new Error("Private or reserved IP addresses are not allowed.");
  u.hash = "";
  return u;
}

// ------------------------------------------------------------ fetching ---
interface Raw { finalUrl: string; contentType: string; body: string }

async function fetchRaw(start: URL): Promise<Raw> {
  let url = start;
  const signal = AbortSignal.timeout(FETCH_TIMEOUT_MS);
  for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
    const res = await fetch(url, {
      dispatcher: safeAgent,
      redirect: "manual",
      signal,
      headers: {
        "user-agent": USER_AGENT,
        accept: "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5",
      },
    });
    if (res.status >= 300 && res.status < 400 && res.headers.get("location")) {
      await res.body?.cancel();
      url = validateUrl(new URL(res.headers.get("location")!, url).toString());
      continue;
    }
    if (!res.ok) {
      await res.body?.cancel();
      throw new Error(`HTTP ${res.status} ${res.statusText} from ${url.host}`);
    }
    const len = Number(res.headers.get("content-length") ?? "0");
    if (len > MAX_BYTES) {
      await res.body?.cancel();
      throw new Error(`Page is ${len} bytes; limit is ${MAX_BYTES}.`);
    }
    const chunks: Uint8Array[] = [];
    let total = 0;
    if (res.body) {
      for await (const chunk of res.body) {
        total += chunk.byteLength;
        if (total > MAX_BYTES) {
          // Keep what we have rather than failing: a truncated page is still useful.
          break;
        }
        chunks.push(chunk);
      }
    }
    const body = Buffer.concat(chunks).toString("utf8");
    return { finalUrl: url.toString(), contentType: (res.headers.get("content-type") ?? "").toLowerCase(), body };
  }
  throw new Error(`Too many redirects (>${MAX_REDIRECTS}).`);
}

// ------------------------------------------------------------- parsing ---
interface Section { id: number; level: number; heading: string; blocks: string[]; chars: number }
interface Link { text: string; href: string }
interface Doc {
  url: string;
  title: string;
  description: string;
  kind: "html" | "text" | "json";
  sections: Section[];
  links: Link[];
  json?: unknown;
  totalChars: number;
  truncatedDownload: boolean;
}

const HEADINGS = new Set(["h1", "h2", "h3", "h4", "h5", "h6"]);
const BLOCK_SEL = "p,li,pre,blockquote,td,th,dt,dd,figcaption,summary";
const ALL_SEL = `h1,h2,h3,h4,h5,h6,${BLOCK_SEL}`;
const clean = (s: string) => s.replace(/\s+/g, " ").trim();

class DocBuilder {
  sections: Section[] = [];
  private cur: Section | null = null;
  heading(level: number, text: string) {
    if (!text) return;
    this.cur = { id: this.sections.length, level, heading: text.slice(0, 200), blocks: [], chars: 0 };
    this.sections.push(this.cur);
  }
  block(text: string) {
    if (!text) return;
    if (!this.cur) this.heading(0, "(intro)");
    this.cur!.blocks.push(text);
    this.cur!.chars += text.length + 2;
  }
  finish(): Section[] {
    // Drop empty heading-only sections only when they have no blocks AND are
    // immediately followed by a deeper heading? No - keep them: they show structure.
    return this.sections;
  }
}

function parseHtml(raw: Raw): Doc {
  const $ = cheerio.load(raw.body);
  const title = clean($("title").first().text()) || clean($("h1").first().text());
  const description = clean(
    $('meta[name="description"]').attr("content") ?? $('meta[property="og:description"]').attr("content") ?? "",
  );

  // Links first (before we strip nav etc.) so navigation stays possible.
  const links: Link[] = [];
  const seen = new Set<string>();
  $("a[href]").each((_, el) => {
    const href = $(el).attr("href") ?? "";
    let abs: URL;
    try {
      abs = new URL(href, raw.finalUrl);
    } catch {
      return;
    }
    if (abs.protocol !== "http:" && abs.protocol !== "https:") return;
    abs.hash = "";
    const key = abs.toString();
    if (seen.has(key)) return;
    seen.add(key);
    links.push({ text: clean($(el).text()).slice(0, 120) || clean($(el).attr("title") ?? ""), href: key });
  });

  $("script,style,noscript,svg,iframe,template,form,nav,footer,header,aside,[hidden],[aria-hidden=true]").remove();
  const rootSel = $("main").length ? "main" : $("article").length ? "article" : "body";
  const root = $(rootSel).first();

  const b = new DocBuilder();
  root.find(ALL_SEL).each((_, el) => {
    const tag = (el as any).tagName?.toLowerCase?.() ?? "";
    const $el = $(el);
    if (HEADINGS.has(tag)) {
      if ($el.parents("h1,h2,h3,h4,h5,h6").length) return;
      b.heading(Number(tag[1]), clean($el.text()));
      return;
    }
    // Keep only the outermost block so nested <li><p> isn't duplicated.
    if ($el.parents(BLOCK_SEL).length) return;
    if (tag === "pre") {
      const t = $el.text().replace(/\s+$/g, "");
      if (t.trim()) b.block("```\n" + t + "\n```");
      return;
    }
    const t = clean($el.text());
    if (!t) return;
    b.block(tag === "li" ? `- ${t}` : tag === "blockquote" ? `> ${t}` : t);
  });

  let sections = b.finish();
  const extracted = sections.reduce((n, s) => n + s.chars, 0);
  // Fallback for div-soup pages with no semantic blocks.
  if (extracted < 200) {
    const fb = new DocBuilder();
    root.text().split(/\n\s*\n|\r\n\s*\r\n/).map(clean).filter(Boolean).forEach((t) => fb.block(t));
    if (fb.sections.reduce((n, s) => n + s.chars, 0) > extracted) sections = fb.finish();
  }
  return finalize({ url: raw.finalUrl, title, description, kind: "html", sections, links });
}

function parseText(raw: Raw): Doc {
  const b = new DocBuilder();
  for (const para of raw.body.split(/\r?\n\s*\r?\n/)) {
    const lines = para.split(/\r?\n/);
    let buf: string[] = [];
    for (const line of lines) {
      const m = /^(#{1,6})\s+(.*)$/.exec(line);
      if (m) {
        if (buf.length) b.block(buf.join("\n").trim());
        buf = [];
        b.heading(m[1].length, m[2].trim());
      } else buf.push(line);
    }
    if (buf.join("").trim()) b.block(buf.join("\n").trim());
  }
  return finalize({ url: raw.finalUrl, title: "", description: "", kind: "text", sections: b.finish(), links: [] });
}

function parseJson(raw: Raw): Doc {
  let json: unknown;
  try {
    json = JSON.parse(raw.body);
  } catch {
    return parseText(raw);
  }
  const b = new DocBuilder();
  b.heading(0, "(json)");
  b.block(JSON.stringify(json, null, 1));
  return finalize({ url: raw.finalUrl, title: "", description: "", kind: "json", sections: b.finish(), links: [], json });
}

function finalize(d: Omit<Doc, "totalChars" | "truncatedDownload">): Doc {
  return { ...d, totalChars: d.sections.reduce((n, s) => n + s.chars, 0), truncatedDownload: false };
}

function parse(raw: Raw): Doc {
  const ct = raw.contentType;
  const looksJson = /^\s*[\[{]/.test(raw.body.slice(0, 50));
  let doc: Doc;
  if (ct.includes("json") || (!ct.includes("html") && looksJson)) doc = parseJson(raw);
  else if (ct.includes("html") || ct.includes("xml") || /^\s*</.test(raw.body.slice(0, 100))) doc = parseHtml(raw);
  else doc = parseText(raw);
  doc.truncatedDownload = Buffer.byteLength(raw.body) >= MAX_BYTES - 65536;
  return doc;
}

// --------------------------------------------------------------- cache ---
const cache = new Map<string, { at: number; doc: Promise<Doc> }>();

function getDoc(rawUrl: string): Promise<Doc> {
  const url = validateUrl(rawUrl);
  const key = url.toString();
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
    cache.delete(key);
    cache.set(key, hit); // LRU bump
    return hit.doc;
  }
  const doc = fetchRaw(url).then(parse);
  cache.set(key, { at: Date.now(), doc });
  doc.catch(() => cache.delete(key)); // never cache failures
  while (cache.size > CACHE_MAX_ENTRIES) cache.delete(cache.keys().next().value!);
  return doc;
}

// ------------------------------------------------------------- helpers ---
const tok = (chars: number) => Math.ceil(chars / 4);
const ok = (text: string) => ({ content: [{ type: "text" as const, text }] });
function errText(e: unknown): string {
  if (!(e instanceof Error)) return String(e);
  if (e.name === "TimeoutError" || e.name === "AbortError") return `Timed out after ${FETCH_TIMEOUT_MS} ms.`;
  const cause = (e as { cause?: unknown }).cause;
  return cause instanceof Error ? `${e.message}: ${cause.message}` : e.message;
}
const fail = (e: unknown) => ({
  isError: true,
  content: [{ type: "text" as const, text: `Error: ${errText(e)}` }],
});
async function run(fn: () => Promise<string>) {
  try {
    return ok(await fn());
  } catch (e) {
    return fail(e);
  }
}
function sectionText(s: Section): string {
  const head = s.level > 0 ? `${"#".repeat(Math.min(s.level, 6))} ${s.heading}\n\n` : "";
  return head + s.blocks.join("\n\n");
}
function page(text: string, offset: number, max: number): string {
  if (offset >= text.length && text.length > 0) return `[offset ${offset} is past the end; total ${text.length} chars]`;
  const end = Math.min(text.length, offset + max);
  let out = text.slice(offset, end);
  if (end < text.length) out += `\n\n[showing chars ${offset}-${end} of ${text.length}; call again with offset=${end} for more]`;
  else if (offset > 0) out += `\n\n[end - chars ${offset}-${end} of ${text.length}]`;
  return out;
}

// ---- JSON path picking: a.b[0].c, items[*].name, [*].id ----
function pathTokens(p: string): (string | number | "*")[] {
  const out: (string | number | "*")[] = [];
  const re = /\[(\d+|\*)\]|([^.[\]]+)/g;
  let m: RegExpExecArray | null;
  let consumed = 0;
  while ((m = re.exec(p))) {
    consumed += m[0].length;
    if (m[1] !== undefined) out.push(m[1] === "*" ? "*" : Number(m[1]));
    else out.push(m[2] === "*" ? "*" : m[2]);
  }
  if (consumed + (p.match(/\./g)?.length ?? 0) !== p.length) throw new Error(`Bad path syntax: ${p}`);
  return out;
}
function pick(root: unknown, p: string): { values: unknown[]; multi: boolean } {
  const toks = pathTokens(p);
  let vals: unknown[] = [root];
  let multi = false;
  for (const t of toks) {
    const next: unknown[] = [];
    for (const v of vals) {
      if (v === null || typeof v !== "object") continue;
      if (t === "*") {
        multi = true;
        next.push(...(Array.isArray(v) ? v : Object.values(v)));
      } else if (typeof t === "number") {
        if (Array.isArray(v) && t < v.length) next.push(v[t]);
      } else if (Object.prototype.hasOwnProperty.call(v, t)) {
        next.push((v as Record<string, unknown>)[t]);
      }
    }
    vals = next;
  }
  return { values: vals, multi };
}
function trim(v: unknown, maxItems: number, depth = 0): unknown {
  if (typeof v === "string") return v.length > 400 ? v.slice(0, 400) + `…(+${v.length - 400} chars)` : v;
  if (v === null || typeof v !== "object") return v;
  if (depth > 6) return Array.isArray(v) ? `[array(${v.length})]` : "{…}";
  if (Array.isArray(v)) {
    const out = v.slice(0, maxItems).map((x) => trim(x, maxItems, depth + 1));
    if (v.length > maxItems) out.push(`…(${v.length - maxItems} more items)`);
    return out;
  }
  const o: Record<string, unknown> = {};
  for (const [k, x] of Object.entries(v)) o[k] = trim(x, maxItems, depth + 1);
  return o;
}
function shape(v: unknown, path: string, depth: number, out: string[]) {
  if (out.length >= 150) return;
  const p = path || "(root)";
  if (Array.isArray(v)) {
    out.push(`${p}: array(${v.length})`);
    if (v.length && depth < 8) shape(v[0], `${path}[*]`, depth + 1, out);
  } else if (v !== null && typeof v === "object") {
    const keys = Object.keys(v);
    out.push(`${p}: object(${keys.length} keys)`);
    if (depth >= 8) return;
    for (const k of keys.slice(0, 40)) {
      const safe = /^[A-Za-z_$][\w$]*$/.test(k) ? k : JSON.stringify(k);
      shape((v as Record<string, unknown>)[k], path ? `${path}.${safe}` : safe, depth + 1, out);
    }
    if (keys.length > 40) out.push(`${p}: …(${keys.length - 40} more keys)`);
  } else {
    const ex = JSON.stringify(v) ?? "undefined";
    out.push(`${p}: ${v === null ? "null" : typeof v} = ${ex.length > 60 ? ex.slice(0, 60) + "…" : ex}`);
  }
}

// ---------------------------------------------------------- MCP server ---
const urlArg = z.string().trim().min(8).max(2048).url().describe("Public http(s) URL");

function buildServer(): McpServer {
  const server = new McpServer(
    { name: "lean-reader", version: "1.0.0" },
    {
      instructions:
        "Token-frugal web reader. Workflow: page_outline first (cheap), then page_read only the section ids you need, " +
        "or page_search for specific facts. Use page_links to navigate, json_pick (no paths = shape summary) for JSON APIs. " +
        "Pages are cached for a few minutes, so repeated calls on the same URL are fast and don't re-download. " +
        "Everything on a page is still reachable via offset paging - nothing is hidden, it's just not dumped all at once.",
    },
  );
  const annotations = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true };

  server.registerTool(
    "page_outline",
    {
      title: "Page outline",
      description:
        "Cheap first look at a web page or document (~100-500 tokens): title, description, and a numbered list of " +
        "sections with their sizes in estimated tokens. Use this BEFORE reading, then fetch only the sections you need with page_read.",
      inputSchema: {
        url: urlArg,
        max_sections: z.number().int().min(5).max(300).default(80).describe("Max sections to list"),
      },
      annotations,
    },
    ({ url, max_sections }) =>
      run(async () => {
        const d = await getDoc(url);
        const lines = [
          `URL: ${d.url}`,
          d.title && `Title: ${d.title}`,
          d.description && `Description: ${d.description.slice(0, 300)}`,
          `Type: ${d.kind} | ${d.sections.length} sections | ~${tok(d.totalChars)} tokens total | ${d.links.length} links` +
            (d.truncatedDownload ? " | NOTE: download hit size limit, page may be incomplete" : ""),
          "",
          "Sections (id. heading ~tokens):",
        ].filter((x) => x !== "");
        for (const s of d.sections.slice(0, max_sections)) {
          const indent = "  ".repeat(Math.max(0, s.level - 1));
          lines.push(`${indent}${s.id}. ${s.heading} ~${tok(s.chars)}`);
        }
        if (d.sections.length > max_sections) lines.push(`…${d.sections.length - max_sections} more sections (raise max_sections)`);
        if (d.kind === "json") lines.push("", "Tip: this is JSON - use json_pick for a shape summary or specific fields.");
        return lines.join("\n");
      }),
  );

  server.registerTool(
    "page_read",
    {
      title: "Read page sections",
      description:
        "Read clean text (no HTML/scripts/nav) from a page. Pass section ids from page_outline to read only those; omit " +
        "to read from the top. Output is paginated: if truncated, call again with the given offset to continue.",
      inputSchema: {
        url: urlArg,
        sections: z.array(z.number().int().min(0).max(100000)).max(50).optional().describe("Section ids from page_outline"),
        include_subsections: z.boolean().default(true).describe("Also include deeper sections nested under each chosen heading"),
        offset: z.number().int().min(0).max(50_000_000).default(0).describe("Character offset for paging"),
        max_chars: z.number().int().min(200).max(40000).default(6000).describe("Max characters to return (≈ chars/4 tokens)"),
      },
      annotations,
    },
    ({ url, sections, include_subsections, offset, max_chars }) =>
      run(async () => {
        const d = await getDoc(url);
        let chosen: Section[];
        if (!sections || sections.length === 0) chosen = d.sections;
        else {
          const ids = new Set<number>();
          for (const id of sections) {
            const s = d.sections[id];
            if (!s) throw new Error(`No section ${id}; page has ids 0-${d.sections.length - 1}.`);
            ids.add(id);
            if (include_subsections && s.level > 0) {
              for (let j = id + 1; j < d.sections.length && d.sections[j].level > s.level; j++) ids.add(j);
            }
          }
          chosen = [...ids].sort((a, b) => a - b).map((i) => d.sections[i]);
        }
        const text = chosen.map(sectionText).join("\n\n");
        return page(text, offset, max_chars) || "(no text content)";
      }),
  );

  server.registerTool(
    "page_search",
    {
      title: "Search within a page",
      description:
        "Find the paragraphs on a page that match keywords, with their section headings and optional neighbouring " +
        "paragraphs for context. Best for pulling a specific fact out of a long page without reading it all.",
      inputSchema: {
        url: urlArg,
        query: z.string().trim().min(2).max(200).describe("Keywords or a phrase"),
        max_matches: z.number().int().min(1).max(30).default(6),
        context: z.number().int().min(0).max(3).default(0).describe("Neighbouring paragraphs to include on each side"),
      },
      annotations,
    },
    ({ url, query, max_matches, context }) =>
      run(async () => {
        const d = await getDoc(url);
        const phrase = query.toLowerCase().replace(/["']/g, "").trim();
        const terms = [...new Set(phrase.split(/[^\p{L}\p{N}_$.-]+/u).filter((t) => t.length >= 2))].slice(0, 12);
        if (!terms.length) throw new Error("Query needs at least one word of 2+ characters.");
        type Hit = { s: number; b: number; score: number };
        const hits: Hit[] = [];
        d.sections.forEach((s, si) =>
          s.blocks.forEach((blk, bi) => {
            const low = (s.heading + " " + blk).toLowerCase();
            let score = 0;
            for (const t of terms) if (low.includes(t)) score++;
            if (terms.length > 1 && low.includes(phrase)) score += 2;
            if (score > 0) hits.push({ s: si, b: bi, score });
          }),
        );
        if (!hits.length) return `No matches for "${query}" in ${d.sections.length} sections. Try page_outline or other words.`;
        const best = [...hits].sort((a, b) => b.score - a.score || a.s - b.s || a.b - b.b).slice(0, max_matches);
        best.sort((a, b) => a.s - b.s || a.b - b.b);
        const snip = (t: string) => {
          if (t.length <= 900) return t;
          const i = Math.max(0, t.toLowerCase().indexOf(terms[0]) - 300);
          return (i > 0 ? "…" : "") + t.slice(i, i + 900) + "…";
        };
        const out = [`${hits.length} matching paragraphs, showing ${best.length} best (terms: ${terms.join(", ")}):`];
        for (const h of best) {
          const s = d.sections[h.s];
          const from = Math.max(0, h.b - context);
          const to = Math.min(s.blocks.length - 1, h.b + context);
          const body = s.blocks.slice(from, to + 1).map(snip).join("\n");
          out.push(`\n[section ${s.id}: ${s.heading}]\n${body}`);
        }
        return out.join("\n");
      }),
  );

  server.registerTool(
    "page_links",
    {
      title: "List page links",
      description:
        "List links on a page (absolute URLs, de-duplicated), optionally filtered by words in the link text or URL. " +
        "Use to navigate a site without reading whole pages.",
      inputSchema: {
        url: urlArg,
        filter: z.string().trim().max(100).optional().describe("Only links whose text or URL contains this (case-insensitive)"),
        same_site_only: z.boolean().default(false),
        max_links: z.number().int().min(1).max(300).default(40),
      },
      annotations,
    },
    ({ url, filter, same_site_only, max_links }) =>
      run(async () => {
        const d = await getDoc(url);
        const host = new URL(d.url).hostname;
        const f = filter?.toLowerCase();
        const list = d.links.filter(
          (l) =>
            (!f || l.text.toLowerCase().includes(f) || l.href.toLowerCase().includes(f)) &&
            (!same_site_only || new URL(l.href).hostname === host),
        );
        if (!list.length) return `No links found${f ? ` matching "${filter}"` : ""}.`;
        const lines = list.slice(0, max_links).map((l) => `- ${l.text || "(no text)"} → ${l.href}`);
        if (list.length > max_links) lines.push(`…${list.length - max_links} more (raise max_links or add a filter)`);
        return `${list.length} links:\n${lines.join("\n")}`;
      }),
  );

  server.registerTool(
    "json_pick",
    {
      title: "Pick fields from JSON",
      description:
        "Fetch a public JSON API/file and return only what you need. With no paths: a compact shape summary " +
        "(every key path, type and example value). With paths like 'data.items[*].name' or 'results[0]': only those values, " +
        "with long arrays/strings trimmed.",
      inputSchema: {
        url: urlArg,
        paths: z
          .array(z.string().trim().min(1).max(200).regex(/^[\w$\-.[\]*\s]+$/, "Use dot/bracket paths like a.b[0].c or items[*].id"))
          .max(20)
          .optional(),
        max_items: z.number().int().min(1).max(500).default(20).describe("Max array items shown per array"),
        max_chars: z.number().int().min(200).max(40000).default(6000),
      },
      annotations,
    },
    ({ url, paths, max_items, max_chars }) =>
      run(async () => {
        const d = await getDoc(url);
        if (d.kind !== "json") throw new Error(`That URL returned ${d.kind}, not JSON. Use page_outline/page_read instead.`);
        if (!paths || paths.length === 0) {
          const lines: string[] = [];
          shape(d.json, "", 0, lines);
          return page(`JSON shape of ${d.url} (arrays show their first item):\n` + lines.join("\n"), 0, max_chars);
        }
        const result: Record<string, unknown> = {};
        for (const p of paths) {
          const { values, multi } = pick(d.json, p);
          result[p] = trim(multi ? values : values.length ? values[0] : null, max_items);
        }
        return page(JSON.stringify(result, null, 1), 0, max_chars);
      }),
  );

  return server;
}

// ---------------------------------------------------------------- HTTP ---
const app = express();
app.disable("x-powered-by");
app.set("trust proxy", 1);
app.use(express.json({ limit: "1mb" }));

const hash = (s: string) => createHash("sha256").update(s).digest();
function auth(req: Request, res: Response, next: NextFunction) {
  if (!SECRET) return next();
  const bearer = /^Bearer\s+(.+)$/i.exec(req.get("authorization") ?? "")?.[1];
  const given = (req.params as Record<string, string>).secret ?? bearer ?? "";
  if (given && timingSafeEqual(hash(given), hash(SECRET))) return next();
  res.status(401).json({ jsonrpc: "2.0", error: { code: -32001, message: "Unauthorized" }, id: null });
}

const hitsByIp = new Map<string, { start: number; n: number }>();
function rateLimit(req: Request, res: Response, next: NextFunction) {
  const ip = req.ip ?? "unknown";
  const now = Date.now();
  const e = hitsByIp.get(ip);
  if (!e || now - e.start > 60_000) hitsByIp.set(ip, { start: now, n: 1 });
  else if (++e.n > RATE_LIMIT) {
    res.status(429).json({ jsonrpc: "2.0", error: { code: -32002, message: "Rate limit exceeded" }, id: null });
    return;
  }
  if (hitsByIp.size > 10_000) hitsByIp.clear();
  next();
}

async function handleMcp(req: Request, res: Response) {
  try {
    const server = buildServer();
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on("close", () => {
      void transport.close();
      void server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (err) {
    console.error("MCP request failed:", err);
    if (!res.headersSent) {
      res.status(500).json({ jsonrpc: "2.0", error: { code: -32603, message: "Internal server error" }, id: null });
    }
  }
}
const methodNotAllowed = (_req: Request, res: Response) => {
  res.status(405).set("Allow", "POST").json({ jsonrpc: "2.0", error: { code: -32000, message: "Method not allowed (stateless server)" }, id: null });
};

const mcpPaths = SECRET ? ["/mcp/:secret", "/mcp"] : ["/mcp"];
app.post(mcpPaths, rateLimit, auth, handleMcp);
app.get(mcpPaths, methodNotAllowed);
app.delete(mcpPaths, methodNotAllowed);
app.get("/", (_req, res) => {
  res.type("text/plain").send("lean-reader MCP server is running. MCP endpoint: POST /mcp" + (SECRET ? "/<secret>" : ""));
});

app.listen(PORT, () => {
  console.log(`lean-reader MCP listening on http://localhost:${PORT}/mcp${SECRET ? "/<CONNECTOR_SECRET>" : ""}`);
  if (!SECRET) console.warn("WARNING: CONNECTOR_SECRET is not set - anyone who knows this URL can use the server.");
});
