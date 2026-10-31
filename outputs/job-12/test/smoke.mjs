// Smoke test: starts the built server, calls every tool, checks auth + SSRF blocking.
// Usage: npm run build && node test/smoke.mjs
import { spawn } from "node:child_process";

const PORT = 8799;
const SECRET = "testsecret";
const srv = spawn(process.execPath, ["dist/server.js"], {
  env: { ...process.env, PORT: String(PORT), CONNECTOR_SECRET: SECRET },
  stdio: ["ignore", "inherit", "inherit"],
});
const base = `http://localhost:${PORT}`;
const headers = { "content-type": "application/json", accept: "application/json, text/event-stream" };

async function waitUp() {
  for (let i = 0; i < 40; i++) {
    try { if ((await fetch(base)).ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("server did not start");
}
async function rpc(method, params, path = `/mcp/${SECRET}`) {
  const r = await fetch(base + path, { method: "POST", headers, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  return { status: r.status, body: await r.json().catch(() => null) };
}
async function call(name, args) {
  const { body } = await rpc("tools/call", { name, arguments: args });
  const text = body?.result?.content?.[0]?.text ?? JSON.stringify(body);
  console.log(`\n=== ${name} ${JSON.stringify(args)}\n${body?.result?.isError ? "[isError] " : ""}${text.slice(0, 1200)}`);
  return body?.result;
}

let failures = 0;
const expect = (cond, msg) => { if (!cond) { failures++; console.log(`FAIL: ${msg}`); } else console.log(`ok: ${msg}`); };

try {
  await waitUp();
  expect((await rpc("tools/list", {}, "/mcp")).status === 401, "no secret -> 401");
  const list = await rpc("tools/list", {});
  const names = list.body?.result?.tools?.map((t) => t.name) ?? [];
  console.log("tools:", names.join(", "));
  const defChars = JSON.stringify(list.body?.result?.tools ?? []).length;
  console.log(`tool definitions: ${defChars} chars (~${Math.round(defChars / 4)} tokens of context while enabled)`);
  expect(names.length === 5, "5 tools listed");

  const wiki = "https://en.wikipedia.org/wiki/Model_Context_Protocol";
  expect(!(await call("page_outline", { url: wiki, max_sections: 15 }))?.isError, "page_outline works");
  expect(!(await call("page_search", { url: wiki, query: "Anthropic November 2024", max_matches: 2 }))?.isError, "page_search works");
  expect(!(await call("page_read", { url: wiki, sections: [1], max_chars: 500 }))?.isError, "page_read works");
  const links = await call("page_links", { url: wiki, filter: "anthropic", same_site_only: true, max_links: 3 });
  expect(!links?.isError && /→ https:\/\//.test(links?.content?.[0]?.text ?? ""), "page_links works");
  const gh = "https://api.github.com/repos/modelcontextprotocol/typescript-sdk";
  expect(!(await call("json_pick", { url: gh }))?.isError, "json_pick shape works");
  expect(!(await call("json_pick", { url: gh, paths: ["full_name", "stargazers_count", "owner.login", "topics"] }))?.isError, "json_pick paths work");

  expect((await call("page_outline", { url: "http://169.254.169.254/latest/meta-data" }))?.isError, "metadata IP blocked");
  expect((await call("page_outline", { url: "http://localtest.me/" }))?.isError, "DNS -> 127.0.0.1 blocked");
  expect((await call("page_outline", { url: "http://[::1]/" }))?.isError, "IPv6 loopback blocked");
  expect((await call("page_outline", { url: "http://[::ffff:127.0.0.1]/" }))?.isError, "IPv4-mapped loopback blocked");
  expect((await call("page_outline", { url: "http://[::ffff:a9fe:a9fe]/" }))?.isError, "IPv4-mapped metadata (hex) blocked");
  const bad = await rpc("tools/call", { name: "page_outline", arguments: { url: "ftp://example.com" } });
  expect(bad.body?.result?.isError || bad.body?.error, "ftp rejected");
} catch (e) {
  failures++;
  console.error(e);
} finally {
  srv.kill();
}
console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL CHECKS PASSED");
process.exit(failures ? 1 : 0);
