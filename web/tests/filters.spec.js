// Filters (T111; US4, FR-036-FR-038, contracts/site-urls.md), against the fixture site:
// six events, built by discovery/tests/web_fixture.py "as of" Oct 1, 2026 and served on 4174.
//
//   Lincoln Security Meetup        lincoln   security        Nov 4    summary: threat modeling
//   Omaha AI Night                 omaha     ai-ml           Nov 10
//   Remote Rust Hour               online    software-dev    Nov 12   organizer: Heartland Rustaceans
//   Omaha Cloud Day                omaha     cloud-devops    Nov 18
//   Lincoln AI & Security Summit   lincoln   ai-ml,security  Nov 20-21
//   Kearney Data Workshop          other_ne  data-analytics  Dec 2
//
// and two past events, on /past/ only:
//
//   Lincoln Security Kickoff       lincoln   security        Sep 10
//   Omaha AI Summer Social         omaha     ai-ml           Aug 20

import { expect, test } from "@playwright/test";

test.use({ baseURL: "http://127.0.0.1:4174" });

const ALL = [
  "Lincoln Security Meetup",
  "Omaha AI Night",
  "Remote Rust Hour",
  "Omaha Cloud Day",
  "Lincoln AI & Security Summit",
  "Kearney Data Workshop",
];

// The titles of the event cards on the list that are visible, in order.
const shown = (page) => page.locator("ol.events article.event:visible h3").allInnerTexts();

async function expectShown(page, titles) {
  await expect.poll(() => shown(page)).toEqual(titles);
}

test.describe("on the list", () => {
  test("with no filters every event shows", async ({ page }) => {
    await page.goto("/");
    await expectShown(page, ALL);
  });

  test("area=lincoln shows only Lincoln events", async ({ page }) => {
    await page.goto("/?area=lincoln");
    await expectShown(page, ["Lincoln Security Meetup", "Lincoln AI & Security Summit"]);
    await expect(page.getByRole("checkbox", { name: "Lincoln area" })).toBeChecked();
  });

  test("several areas show events in any of them", async ({ page }) => {
    await page.goto("/?area=online,other_ne");
    await expectShown(page, ["Remote Rust Hour", "Kearney Data Workshop"]);
  });

  test("cat=security,ai-ml shows events in either category", async ({ page }) => {
    await page.goto("/?cat=security,ai-ml");
    await expectShown(page, ["Lincoln Security Meetup", "Omaha AI Night", "Lincoln AI & Security Summit"]);
  });

  test("from and to limit the dates, and a two-day event counts on either day", async ({ page }) => {
    await page.goto("/?from=2026-11-10&to=2026-11-18");
    await expectShown(page, ["Omaha AI Night", "Remote Rust Hour", "Omaha Cloud Day"]);
    await page.goto("/?from=2026-11-21&to=2026-11-21");
    await expectShown(page, ["Lincoln AI & Security Summit"]);
  });

  test("q matches the title, the organizer and the summary", async ({ page }) => {
    await page.goto("/?q=ai%20night");
    await expectShown(page, ["Omaha AI Night"]);
    await page.goto("/?q=rustaceans");
    await expectShown(page, ["Remote Rust Hour"]);
    await page.goto("/?q=threat%20modeling");
    await expectShown(page, ["Lincoln Security Meetup"]);
  });

  test("q is cut to 100 characters", async ({ page }) => {
    await page.goto(`/?q=${"x".repeat(150)}`);
    await expect(page.getByRole("searchbox", { name: "Search" })).toHaveValue("x".repeat(100));
    await expectShown(page, []);
  });

  test("filters combine", async ({ page }) => {
    await page.goto("/?area=lincoln&cat=ai-ml");
    await expectShown(page, ["Lincoln AI & Security Summit"]);
  });

  test("the result count is announced", async ({ page }) => {
    await page.goto("/?area=lincoln");
    await expect(page.getByRole("status")).toHaveText(/2 of 6 events/);
    await page.goto("/?area=lincoln&q=nothing-matches-this");
    await expect(page.getByRole("status")).toHaveText(/No events match/);
  });

  test("invalid values are ignored", async ({ page }) => {
    await page.goto("/?area=mars,lincoln&cat=bogus&from=2026-13-40&to=yesterday&q=");
    await expectShown(page, ["Lincoln Security Meetup", "Lincoln AI & Security Summit"]);
    await page.goto("/?area=mars");
    await expectShown(page, ALL);
  });

  test("changing a control filters and updates the address", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("checkbox", { name: "Omaha area" }).check();
    await expectShown(page, ["Omaha AI Night", "Omaha Cloud Day"]);
    await expect(page).toHaveURL(/[?&]area=omaha(&|$)/);
    await page.getByLabel("Topic", { exact: true }).selectOption("cloud-devops");
    await expectShown(page, ["Omaha Cloud Day"]);
    await expect(page).toHaveURL(/cat=cloud-devops/);
    await page.getByRole("link", { name: "Clear filters" }).click();
    await expectShown(page, ALL);
  });

  test("months with no matching events are hidden", async ({ page }) => {
    await page.goto("/?area=other_ne");
    await expect(page.locator("section.month:visible h2 .month-name")).toHaveText(["December 2026"]);
    await page.goto("/?area=lincoln");
    await expect(page.locator("section.month:visible .month-count")).toHaveText(["2 of 5 events"]);
  });
});

test.describe("on the calendar", () => {
  test("a month page shows only matching entries", async ({ page }) => {
    await page.goto("/calendar/2026/11/?cat=security");
    const titles = await page.locator("li.cal-event:visible .cal-title").allInnerTexts();
    expect([...new Set(titles)]).toEqual(["Lincoln Security Meetup", "Lincoln AI & Security Summit"]);
  });

  test("filters carry from the list to the calendar and across months and weeks", async ({ page }) => {
    await page.goto("/?area=lincoln");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Calendar" }).click();
    await expect(page).toHaveURL(/\/calendar\/2026\/10\/\?area=lincoln$/);
    await page.locator('.cal-nav a[rel="next"]').click();
    await expect(page).toHaveURL(/\/calendar\/2026\/11\/\?area=lincoln$/);
    const titles = await page.locator("li.cal-event:visible .cal-title").allInnerTexts();
    expect([...new Set(titles)]).toEqual(["Lincoln Security Meetup", "Lincoln AI & Security Summit"]);
    await page.getByRole("link", { name: "Week 45" }).click();
    await expect(page).toHaveURL(/\/calendar\/2026\/week\/45\/\?area=lincoln$/);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Upcoming" }).click();
    await expect(page).toHaveURL(/\/\?area=lincoln$/);
    await expectShown(page, ["Lincoln Security Meetup", "Lincoln AI & Security Summit"]);
  });

  test("a reload restores the same view", async ({ page }) => {
    await page.goto("/calendar/2026/11/?area=omaha&q=cloud");
    await page.reload();
    const titles = await page.locator("li.cal-event:visible .cal-title").allInnerTexts();
    expect(titles).toEqual(["Omaha Cloud Day"]);
    await expect(page.getByRole("searchbox", { name: "Search" })).toHaveValue("cloud");
  });
});

test.describe("with JavaScript off", () => {
  test.use({ javaScriptEnabled: false });

  test("every event shows, with a notice that filters need JavaScript", async ({ page }) => {
    await page.goto("/?area=lincoln");
    await expectShown(page, ALL);
    // Playwright's text matchers skip <noscript>; browsers with JavaScript off show it.
    expect(await page.content()).toMatch(/<noscript><p[^>]*>Filters need JavaScript/);
    await expect(page.getByRole("search")).toBeHidden();
  });
});

test.describe("on past events", () => {
  const PAST = ["Lincoln Security Kickoff", "Omaha AI Summer Social"];

  test("past events show most recent first, and not on the list", async ({ page }) => {
    await page.goto("/past/");
    await expectShown(page, PAST);
    await page.goto("/");
    await expect(page.getByText("Lincoln Security Kickoff")).toHaveCount(0);
  });

  test("filters work on /past/", async ({ page }) => {
    await page.goto("/past/?area=lincoln");
    await expectShown(page, ["Lincoln Security Kickoff"]);
    await expect(page.getByRole("status")).toHaveText(/1 of 2 events/);
  });

  test("the Past link keeps the filters from the list", async ({ page }) => {
    await page.goto("/?cat=ai-ml");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Past" }).click();
    await expect(page).toHaveURL(/\/past\/\?cat=ai-ml$/);
    await expectShown(page, ["Omaha AI Summer Social"]);
  });
});
