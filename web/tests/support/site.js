// Build the site for the browser tests and serve it (T154): node tests/support/site.js [port]
//
// Bundles three.js (npm run build:vendor), builds the site from the repo's data/ into
// web/.test-site/ with a fixed "now" so the list always has events, then serves it on 127.0.0.1
// with the headers from web/_headers, so the tests run under the real Content-Security-Policy.

import { execFileSync, execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const DISCOVERY = path.join(WEB, "..", "discovery");
const OUT = path.join(WEB, ".test-site");
const NOW = "2026-10-01T00:00:00Z";
const PORT = Number(process.argv[2] || 4173);
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".woff2": "font/woff2",
  ".webp": "image/webp",
  ".txt": "text/plain; charset=utf-8",
};

execSync("npm run build:vendor", { cwd: WEB, stdio: "inherit" });
execFileSync(
  "uv",
  ["run", "netc", "build-site", "--data", "../data", "--out", OUT, "--web", WEB, "--now", NOW],
  { cwd: DISCOVERY, stdio: "inherit" },
);

// The "/*" block of _headers: one "Name: value" per indented line.
const headers = {};
let inAll = false;
for (const line of readFileSync(path.join(WEB, "_headers"), "utf8").split(/\r?\n/)) {
  if (!line.startsWith(" ")) inAll = line.trim() === "/*";
  else if (inAll && line.includes(":")) {
    const at = line.indexOf(":");
    headers[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
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
    const file = await resolveFile(new URL(req.url, "http://localhost").pathname);
    const target = file || path.join(OUT, "404.html");
    const type = TYPES[path.extname(target)] || "application/octet-stream";
    res.writeHead(file ? 200 : 404, { ...headers, "Content-Type": type });
    res.end(await readFile(target));
  })
  .listen(PORT, "127.0.0.1", () => console.log(`Serving ${OUT} on http://127.0.0.1:${PORT}/`));
