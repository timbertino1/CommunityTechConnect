// The calendar (T110; US3, FR-033, FR-050): keyboard-only use, and the phone agenda. The test
// site is built from data/ as of Oct 1, 2026 (tests/support/site.js), so these use November
// 2026, whose grid also shows Oct 26-31.

import { expect, test } from "@playwright/test";

const NOVEMBER = "/calendar/2026/11/";

// Tab until the focused element matches, returning how many presses it took.
async function tabTo(page, matches, limit = 60) {
  for (let i = 1; i <= limit; i++) {
    await page.keyboard.press("Tab");
    if (await page.evaluate(matches)) return i;
  }
  throw new Error("never reached");
}

test("the skip link is the first stop and moves focus to the content", async ({ page }) => {
  await page.goto(NOVEMBER);
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText("Skip to main content");
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
});

test("every focusable element shows a focus outline", async ({ page }) => {
  await page.goto(NOVEMBER);
  const count = await page.locator("a[href], button, select").count();
  for (let i = 0; i < count; i++) {
    await page.keyboard.press("Tab");
    const outline = await page.evaluate(() => {
      const style = getComputedStyle(document.activeElement);
      return style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
    });
    const which = await page.evaluate(
      () => `${document.activeElement.tagName} "${document.activeElement.textContent.trim()}"`,
    );
    expect(outline, which).toBe(true);
  }
});

test("months and events can be opened with the keyboard alone", async ({ page }) => {
  await page.goto(NOVEMBER);
  await tabTo(page, () => document.activeElement.getAttribute("rel") === "next");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/calendar\/2026\/12\/$/);

  await page.goto(NOVEMBER);
  await tabTo(page, () => (document.activeElement.getAttribute("href") || "").startsWith("/events/"));
  const href = await page.evaluate(() => document.activeElement.getAttribute("href"));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`${href}$`));
  await expect(page.getByRole("heading", { level: 1 })).not.toBeEmpty();
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true });

  test("the month lists only its own days that have events", async ({ page }) => {
    await page.goto(NOVEMBER);
    const shown = await page.$$eval("td[data-date]", (cells) =>
      cells.filter((td) => td.offsetParent !== null).map((td) => td.dataset.date),
    );
    expect(shown.length).toBeGreaterThan(0);
    expect(shown.every((day) => day.startsWith("2026-11-"))).toBe(true);
    for (const day of shown) {
      expect(await page.locator(`td[data-date="${day}"] a[href^="/events/"]`).count()).toBeGreaterThan(0);
    }
  });
});
