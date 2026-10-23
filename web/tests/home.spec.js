// The home page and its header map (T154; research R15): the list works without JavaScript,
// the map is still under reduced motion, pauses off screen, and becomes a static image without
// WebGL, under Save-Data or on low-memory devices. three.js is downloaded only when the 3D map is drawn.

import { expect, test } from "@playwright/test";

const THREE = "/vendor/three.js";

// Count animation frames, and record which paths the page requests.
async function watch(page) {
  await page.addInitScript(() => {
    window.__frames = 0;
    const raf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (cb) =>
      raf((t) => {
        window.__frames += 1;
        cb(t);
      });
  });
  const paths = [];
  page.on("request", (r) => paths.push(new URL(r.url()).pathname));
  return paths;
}

const frames = (page) => page.evaluate(() => window.__frames);
const map = (page) => page.locator("[data-header-map]");

async function expectStill(page) {
  const still = map(page).locator("img");
  await expect(still).toBeVisible();
  await expect.poll(() => still.evaluate((img) => img.complete && img.naturalWidth)).toBeGreaterThan(0);
  await expect(map(page).locator("canvas")).toBeHidden();
}

test("the map is decoration: hidden from assistive technology", async ({ page }) => {
  await page.goto("/");
  await expect(map(page)).toHaveAttribute("aria-hidden", "true");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Every Nebraska tech event, in one place.");
});

test("on a desktop the 3D map draws and animates", async ({ page }) => {
  const paths = await watch(page);
  await page.goto("/");
  await expect(map(page).locator("canvas")).toBeVisible();
  const before = await frames(page);
  await page.waitForTimeout(500);
  expect(await frames(page)).toBeGreaterThan(before + 5);
  expect(paths).toContain(THREE);
});

test("the animation pauses while the map is scrolled out of view", async ({ page }) => {
  await watch(page);
  await page.goto("/");
  await expect(map(page).locator("canvas")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(300);
  const offscreen = await frames(page);
  await page.waitForTimeout(700);
  expect(await frames(page)).toBe(offscreen);
});

test.describe("with reduced motion", () => {
  test.use({ reducedMotion: "reduce" });

  test("the map is one still frame, with no animation loop", async ({ page }) => {
    await watch(page);
    await page.goto("/");
    await expect(map(page).locator("canvas")).toBeVisible();
    await page.waitForTimeout(1000);
    expect(await frames(page)).toBe(0);
  });
});

test.describe("without WebGL", () => {
  test("the static image is shown and three.js is never downloaded", async ({ page }) => {
    await page.addInitScript(() => {
      const getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
        return /webgl/i.test(type) ? null : getContext.call(this, type, ...rest);
      };
    });
    const paths = await watch(page);
    await page.goto("/");
    await expectStill(page);
    expect(paths).not.toContain(THREE);
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("the 3D map draws and animates under the title", async ({ page }) => {
    const paths = await watch(page);
    await page.goto("/");
    await expect(map(page).locator("canvas")).toBeVisible();
    const before = await frames(page);
    await page.waitForTimeout(500);
    expect(await frames(page)).toBeGreaterThan(before + 5);
    expect(paths).toContain(THREE);
  });
});

for (const [name, setup] of [
  ["with Save-Data on", () => Object.defineProperty(navigator, "connection", { value: { saveData: true } })],
  ["on a device with under 4 GB of memory", () => Object.defineProperty(navigator, "deviceMemory", { value: 2 })],
]) {
  test.describe(name, () => {
    test("the static image is shown and three.js is never downloaded", async ({ page }) => {
      await page.addInitScript(setup);
      const paths = await watch(page);
      await page.goto("/");
      await expectStill(page);
      expect(paths).not.toContain(THREE);
    });
  });
}

test.describe("with JavaScript off", () => {
  test.use({ javaScriptEnabled: false });

  test("the list and its links work, and no map is shown", async ({ page }) => {
    await page.goto("/");
    const cards = page.locator("ol.events article");
    expect(await cards.count()).toBeGreaterThan(0);
    await expect(map(page).locator("canvas")).toBeHidden();
    await expect(map(page).locator("img")).toBeHidden();

    const first = cards.first();
    await expect(first.locator("a.primary")).toHaveAttribute("href", /^https:\/\//);
    const title = await first.locator("h3 a").innerText();
    await first.locator("h3 a").click();
    await expect(page).toHaveURL(/\/events\/[^/]+\/$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
    await expect(page.locator("a.primary")).toHaveAttribute("href", /^https:\/\//);
  });
});
