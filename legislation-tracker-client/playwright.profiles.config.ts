import { defineConfig, devices } from "@playwright/test";

// Requires separately started isolated frontend13290/API18011. Never starts or
// resets a database, or attaches to the dashboard agent's13280 preview.
export default defineConfig({
  testDir: "./e2e", testMatch: /(?:legislator-profiles|dashboard-cards)\.spec\.ts/,
  fullyParallel: false, workers: 1, retries: 0,
  use: { baseURL: "http://127.0.0.1:13290", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
