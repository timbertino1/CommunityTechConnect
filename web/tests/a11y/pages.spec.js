// axe-core on every kind of page (T136; SC-009, WCAG 2.2 AA), at phone and desktop widths and in
// both color schemes, on the fixture site (tests/support/site.js): it has upcoming and past
// events, an event page and the suggestion form. CI runs this with the other browser tests.

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = {
  home: "/",
  past: "/past/",
  month: "/calendar/2026/11/",
  week: "/calendar/2026/week/46/",
  event: "/events/lincoln-ai-security-summit-2026-11-20/",
  suggest: "/suggest/",
  about: "/about/",
};
// 320 px is where WCAG 2.2 "Reflow" (1.4.10) is measured; 360 px and 1280 px are T136's widths.
const WIDTHS = [320, 360, 1280];
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

test.use({ baseURL: "http://127.0.0.1:4174" });

for (const colorScheme of ["light", "dark"]) {
  for (const width of WIDTHS) {
    test.describe(`${colorScheme}, ${width}px`, () => {
      test.use({ colorScheme, viewport: { width, height: 900 } });

      for (const [name, path] of Object.entries(PAGES)) {
        test(`${name} (${path}) has no axe violations`, async ({ page }) => {
          // The suggestion form's Turnstile script comes from Cloudflare; a stub keeps the test
          // offline (the widget itself is Cloudflare's, inside its own frame).
          await page.route("https://challenges.cloudflare.com/**", (route) =>
            route.fulfill({ status: 200, contentType: "text/javascript", body: "" }),
          );
          const response = await page.goto(path);
          expect(response?.status()).toBe(200);
          const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
          expect(results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`)).toEqual([]);
          expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
        });
      }
    });
  }
}
