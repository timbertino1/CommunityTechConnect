// Home page loader for the header map (T153; research R15). After the page has loaded, show the
// 3D map, or its static image under Save-Data, low device memory (under 4 GB), or no WebGL.
// Phones get the 3D map too (owner decision, 2026-10-22). Nothing here imports three.js:
// header-map.js does, and only when it is used.

const box = document.querySelector("[data-header-map]");
const LOAD_TIMEOUT_MS = 10_000;

if (box) {
  const run = () => idle(() => choose().catch(showStill));
  if (document.readyState === "complete") run();
  else window.addEventListener("load", run, { once: true });
}

function idle(fn) {
  if ("requestIdleCallback" in window) window.requestIdleCallback(fn, { timeout: 2000 });
  else window.setTimeout(fn, 200);
}

function lowPower() {
  const connection = navigator.connection;
  return Boolean(
    (connection && connection.saveData) ||
      (navigator.deviceMemory !== undefined && navigator.deviceMemory < 4),
  );
}

function hasWebGL() {
  try {
    const probe = document.createElement("canvas");
    return Boolean(probe.getContext("webgl2") || probe.getContext("webgl"));
  } catch {
    return false;
  }
}

async function choose() {
  if (lowPower() || !hasWebGL()) {
    showStill();
    return;
  }
  // A stalled download falls back to the image rather than leaving the band empty.
  const [{ start }, data] = await Promise.race([
    Promise.all([
      import("/js/header-map.js"),
      fetch("/data/map.json").then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status)))),
    ]),
    new Promise((_, reject) => window.setTimeout(() => reject(new Error("timeout")), LOAD_TIMEOUT_MS)),
  ]);
  const canvas = box.querySelector("canvas");
  canvas.hidden = false;
  document.querySelector("[data-map-legend]")?.removeAttribute("hidden");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  start(canvas, data, { animate: !reduce });
}

function showStill() {
  box.querySelector("canvas").hidden = true;
  const still = box.querySelector("img");
  still.src = "/img/header-map.webp";
  still.hidden = false;
}
