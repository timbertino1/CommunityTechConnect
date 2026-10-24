// Build the site for the browser tests and serve it (T154): node tests/support/site.js [port] [fixture]
//
// Bundles three.js (npm run build:vendor), builds the site from the repo's data/ into
// web/.test-site/ with a fixed "now" so the list always has events, then serves it on 127.0.0.1
// with the headers from the built _headers, so the tests run under the real Content-Security-Policy.
// With "fixture" it builds the filter tests' fixed events instead (discovery/tests/web_fixture.py,
// T111) into web/.test-fixture/, with the suggestion form pointed at a stand-in Worker host that
// the tests answer themselves (T132), and leaves three.js to the other server.

import { execFileSync, execSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const DISCOVERY = path.join(WEB, "..", "discovery");
const FIXTURE = process.argv[3] === "fixture";
const OUT = path.join(WEB, FIXTURE ? ".test-fixture" : ".test-site");
const NOW = "2026-10-01T12:00:00Z"; // 7 AM on Oct 1 in Omaha (midnight UTC is still Sep 30 there)
const PORT = Number(process.argv[2] || 4173);
const SUGGEST_ENDPOINT = "https://netc-suggest.test.invalid/suggest"; // as in tests/suggest.spec.js
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".woff2": "font/woff2",
  ".webp": "image/webp",
  ".txt": "text/plain; charset=utf-8",
};

let data = "../data";
if (FIXTURE) {
  data = path.join(WEB, ".test-fixture-data");
  rmSync(data, { recursive: true, force: true });
  execFileSync("uv", ["run", "python", "-m", "tests.web_fixture", data], { cwd: DISCOVERY, stdio: "inherit" });
} else {
  execSync("npm run build:vendor", { cwd: WEB, stdio: "inherit" });
}
const suggest = FIXTURE ? ["--suggest-endpoint", SUGGEST_ENDPOINT] : [];
execFileSync(
  "uv",
  ["run", "netc", "build-site", "--data", data, "--out", OUT, "--web", WEB, "--now", NOW, ...suggest],
  { cwd: DISCOVERY, stdio: "inherit" },
);

// The built _headers, applied as Cloudflare Pages does: every block whose path matches adds its
// headers (a repeated name is joined with ", "), and "! Name" removes one an earlier block set.
const rules = [];
for (const line of readFileSync(path.join(OUT, "_headers"), "utf8").split(/\r?\n/)) {
  const text = line.trim();
  if (!text) continue;
  if (!line.startsWith(" ")) rules.push({ pattern: text, set: [], remove: [] });
  else if (text.startsWith("!")) rules.at(-1)?.remove.push(text.slice(1).trim());
  else if (text.includes(":")) {
    const at = text.indexOf(":");
    rules.at(-1)?.set.push([text.slice(0, at).trim(), text.slice(at + 1).trim()]);
  }
}

function headersFor(urlPath) {
  const headers = {};
  for (const rule of rules) {
    const prefix = rule.pattern.endsWith("*") ? rule.pattern.slice(0, -1) : null;
    if (prefix === null ? urlPath !== rule.pattern : !urlPath.startsWith(prefix)) continue;
    for (const name of rule.remove) delete headers[name];
    for (const [name, value] of rule.set) headers[name] = name in headers ? `${headers[name]}, ${value}` : value;
  }
  return headers;
}

async function resolveFile(urlPath) {
  const file = path.join(OUT, decodeURIComponent(urlPath));
  if (!file.startsWith(OUT)) return null;
  const info = await stat(file).catch(() => null);
  if (info?.isDirectory()) return resolveFile(path.posix.join(urlPath, "index.html"));
  return info?.isFile() ? file : null;
}

http
  .createServer(async (req, res) => {
    const urlPath = new URL(req.url, "http://localhost").pathname;
    const file = await resolveFile(urlPath);
    const target = file || path.join(OUT, "404.html");
    const type = TYPES[path.extname(target)] || "application/octet-stream";
    res.writeHead(file ? 200 : 404, { ...headersFor(urlPath), "Content-Type": type });
    res.end(await readFile(target));
  })
  .listen(PORT, "127.0.0.1", () => console.log(`Serving ${OUT} on http://127.0.0.1:${PORT}/`));
