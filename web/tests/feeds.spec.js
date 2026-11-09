// The feeds page and its Follow links (feature 002 T021; specs/002-event-feeds/contracts/feeds.md),
// on the fixture site (tests/support/site.js).

import { expect, test } from "@playwright/test";

test.use({ baseURL: "http://127.0.0.1:4174" });

test("the footer Follow link leads to the feeds page", async ({ page }) => {
  await page.goto("/");
  await page.locator("footer").getByRole("link", { name: "Follow", exact: true }).click();
  await expect(page).toHaveURL(/\/feeds\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Follow new events");
});

test("the home page links to the feeds page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Follow new events" }).click();
  await expect(page).toHaveURL(/\/feeds\/$/);
});

test("the feeds page lists the all-events feed first, then one per topic", async ({ page }) => {
  await page.goto("/feeds/");
  const links = page.locator(".feed-list a");
  await expect(links).toHaveCount(12);
  await expect(links.first()).toHaveAttribute("href", /\/feeds\/all\.xml$/);
  for (const href of await links.evaluateAll((as) => as.map((a) => a.getAttribute("href")))) {
    expect(href).toMatch(/^https:\/\/[^/]+\/feeds\/[a-z0-9-]+\.xml$/);
  }
});

test.describe("at 320 px", () => {
  test.use({ viewport: { width: 320, height: 800 } });

  test("long addresses wrap without sideways scrolling", async ({ page }) => {
    await page.goto("/feeds/");
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  });
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("the feeds page still lists every feed", async ({ page }) => {
    await page.goto("/feeds/");
    await expect(page.locator(".feed-list a")).toHaveCount(12);
  });
});

test("the feed file is served", async ({ request }) => {
  const response = await request.get("/feeds/all.xml");
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('<feed xmlns="http://www.w3.org/2005/Atom">');
});
