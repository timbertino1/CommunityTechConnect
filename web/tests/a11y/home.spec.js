// axe-core on the home page with the header map on (T154), in both color schemes.

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

for (const colorScheme of ["light", "dark"]) {
  test.describe(`${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test("the home page has no axe violations with the map drawn", async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("[data-header-map] canvas")).toBeVisible();
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      expect(results.violations).toEqual([]);
    });
  });
}

for (const path of ["/calendar/2026/11/", "/calendar/2026/week/45/"]) {
  test(`${path} has no axe violations`, async ({ page }) => {
    await page.goto(path);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations).toEqual([]);
  });
}
