// Browser tests for the built site (T154): `npx playwright test` builds it and serves it.
// Set PW_CHANNEL=msedge (or chrome) to use an installed browser instead of Playwright's Chromium.

import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;
// The filter tests' fixed events (T111), served on a second port: see tests/filters.spec.js.
const FIXTURE_PORT = 4174;

export default defineConfig({
  testDir: "tests",
  timeout: 30_000,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        channel: process.env.PW_CHANNEL || undefined,
        // CI runners have no GPU: let WebGL fall back to software rendering.
        launchOptions: { args: ["--enable-unsafe-swiftshader"] },
      },
    },
  ],
  webServer: [
    {
      command: `node tests/support/site.js ${PORT}`,
      url: `http://127.0.0.1:${PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command: `node tests/support/site.js ${FIXTURE_PORT} fixture`,
      url: `http://127.0.0.1:${FIXTURE_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
