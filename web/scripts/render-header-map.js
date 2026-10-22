// Render img/header-map.webp, the header map's static image (T153), from the same scene as
// js/header-map.js: the outline, dot grid and towns, with no pins (a fixed image can't know
// which cities have events next month). Re-run when the outline, the look or the towns change.
//
//   npm run build:vendor
//   (cd ../discovery && uv run netc build-site --data ../data --out ../dist --web ../web)
//   node scripts/render-header-map.js ../dist/data/map.json
//
// Uses Playwright's Chromium; set BROWSER_CHANNEL=msedge (or chrome) to use an installed browser.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "@playwright/test";

const WEB = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OUT = path.join(WEB, "img", "header-map.webp");
const MAX_BYTES = 40 * 1024;
const [width, height] = [900, 520];

const mapJson = process.argv[2];
if (!mapJson) throw new Error("usage: node scripts/render-header-map.js <path to map.json>");
const { towns } = JSON.parse(await readFile(mapJson, "utf8"));

const page_html = `<!doctype html><meta charset="utf-8">
<body style="margin:0;background:transparent">
<canvas id="c" style="width:${width}px;height:${height}px"></canvas>`;

const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || undefined });
try {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.route("http://render.local/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/") return route.fulfill({ contentType: "text/html", body: page_html });
    const file = path.join(WEB, url.pathname);
    if (!file.startsWith(WEB + path.sep)) return route.abort();
    return route.fulfill({ contentType: "text/javascript", body: await readFile(file) });
  });
  await page.goto("http://render.local/");
  for (const quality of [0.85, 0.75, 0.65, 0.55]) {
    const dataUrl = await page.evaluate(
      async ({ towns, quality }) => {
        const { start } = await import("/js/header-map.js");
        const canvas = document.getElementById("c");
        const map = start(canvas, { towns, pins: [] }, { animate: false, centered: true, capture: true });
        const out = canvas.toDataURL("image/webp", quality);
        map.stop();
        return out;
      },
      { towns, quality },
    );
    const bytes = Buffer.from(dataUrl.split(",")[1], "base64");
    if (!dataUrl.startsWith("data:image/webp")) throw new Error("this browser can't encode WebP");
    if (bytes.length <= MAX_BYTES) {
      await mkdir(path.dirname(OUT), { recursive: true });
      await writeFile(OUT, bytes);
      console.log(`wrote ${path.relative(WEB, OUT)}: ${bytes.length} bytes at quality ${quality}`);
      process.exitCode = 0;
      break;
    }
    console.log(`quality ${quality}: ${bytes.length} bytes, over ${MAX_BYTES}`);
    process.exitCode = 1;
  }
} finally {
  await browser.close();
}
