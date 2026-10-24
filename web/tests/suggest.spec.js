// The /suggest/ form (T132; FR-020, contracts/workers.md section 1), on the fixture site, which
// points the form at a stand-in Worker host (tests/support/site.js). The tests answer that host
// and replace Cloudflare's Turnstile script with a stub that adds a token, so nothing leaves the
// machine, while the page runs under its real Content-Security-Policy.

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const SITE = "http://127.0.0.1:4174";
const ENDPOINT = "https://netc-suggest.test.invalid/suggest";
const TURNSTILE = "https://challenges.cloudflare.com/turnstile/v0/api.js";

const FAKE_TURNSTILE = `
for (const box of document.querySelectorAll(".cf-turnstile")) {
  const token = document.createElement("input");
  token.type = "hidden";
  token.name = "cf-turnstile-response";
  token.value = "fake-token";
  box.append(token);
}
window.turnstile = { resets: 0, reset() { this.resets += 1; } };
`;

test.use({ baseURL: SITE });

async function open(page, { turnstile = FAKE_TURNSTILE } = {}) {
  await page.route(TURNSTILE, (route) =>
    route.fulfill({ status: 200, contentType: "text/javascript", body: turnstile }),
  );
  await page.goto("/suggest/");
}

function worker(page, status, { abort = false } = {}) {
  const sent = [];
  page.route(ENDPOINT, (route) => {
    sent.push(route.request().postData());
    if (abort) return route.abort();
    return route.fulfill({
      status,
      headers: { "access-control-allow-origin": SITE, "content-type": "application/json" },
      body: JSON.stringify({ status: "whatever" }),
    });
  });
  return sent;
}

async function fillAndSend(page) {
  await page.getByLabel("Web address").fill("https://www.meetup.com/omaha-rust/");
  await page.getByLabel("Note (optional)").fill("Monthly, downtown.");
  await page.getByRole("button", { name: "Send suggestion" }).click();
}

test("a suggestion is sent with its token and confirmed", async ({ page }) => {
  await open(page);
  const sent = worker(page, 202);
  await fillAndSend(page);
  await expect(page.getByRole("status")).toHaveText(/Thanks! We'll take a look/);
  const body = new URLSearchParams(sent[0]);
  expect(body.get("url")).toBe("https://www.meetup.com/omaha-rust/");
  expect(body.get("note")).toBe("Monthly, downtown.");
  expect(body.get("cf-turnstile-response")).toBe("fake-token");
  await expect(page.getByLabel("Web address")).toHaveValue("");
  expect(await page.evaluate(() => window.turnstile.resets)).toBe(1);
});

for (const [status, message] of [
  [400, /didn't go through/],
  [429, /try again later/],
  [500, /couldn't send that/],
]) {
  test(`a ${status} answer says so without repeating the address`, async ({ page }) => {
    await open(page);
    worker(page, status);
    await fillAndSend(page);
    await expect(page.getByRole("status")).toHaveText(message);
    await expect(page.getByRole("status")).not.toContainText("meetup.com");
    await expect(page.getByLabel("Web address")).toHaveValue("https://www.meetup.com/omaha-rust/");
  });
}

test("a network failure is reported", async ({ page }) => {
  await open(page);
  worker(page, 0, { abort: true });
  await fillAndSend(page);
  await expect(page.getByRole("status")).toHaveText(/couldn't send that/);
});

test("without a Turnstile token nothing is sent", async ({ page }) => {
  await open(page, { turnstile: "window.turnstile = { reset() {} };" });
  const sent = worker(page, 202);
  await fillAndSend(page);
  await expect(page.getByRole("status")).toHaveText(/wait for the spam check/);
  expect(sent).toEqual([]);
});

test("the page has its own CSP that allows Turnstile and the Worker, and only there", async ({ page, request }) => {
  const suggest = (await request.get("/suggest/")).headers()["content-security-policy"];
  expect(suggest).toContain("script-src 'self' https://challenges.cloudflare.com;");
  expect(suggest).toContain("connect-src 'self' https://netc-suggest.test.invalid;");
  expect(suggest).not.toContain(", default-src"); // the site-wide CSP was removed, not added to
  const home = (await request.get("/")).headers()["content-security-policy"];
  expect(home).not.toContain("challenges.cloudflare.com");

  const blocked = [];
  page.on("console", (msg) => {
    if (/Content Security Policy/i.test(msg.text())) blocked.push(msg.text());
  });
  await open(page);
  await expect.poll(() => page.evaluate(() => typeof window.turnstile)).toBe("object");
  expect(blocked).toEqual([]);
});

test("the footer links to the form", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Footer" }).getByRole("link", { name: "Suggest a group" }).click();
  await expect(page).toHaveURL(/\/suggest\/$/);
});

test("/suggest/ has no axe violations", async ({ page }) => {
  await open(page);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
});

test("on a phone the form fits", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});
