// Fail if the header map's script, three.js included, exceeds 150 KB gzipped (T154; research R15
// limit 2). Run after `npm run build:vendor`.

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { constants, gzipSync } from "node:zlib";

const WEB = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const BUDGET = 150 * 1024;
const FILES = ["js/header-map.js", "vendor/three.js"];

let total = 0;
for (const file of FILES) {
  const size = gzipSync(readFileSync(path.join(WEB, file)), { level: constants.Z_BEST_COMPRESSION }).length;
  total += size;
  console.log(`${file}: ${(size / 1024).toFixed(1)} KB gzipped`);
}
console.log(`total: ${(total / 1024).toFixed(1)} KB of ${BUDGET / 1024} KB`);
if (total > BUDGET) {
  console.error("The header map is over its 150 KB budget (research R15). Trim web/vendor-src/three.js.");
  process.exitCode = 1;
}
