import { defineConfig, devices } from "@playwright/test";
export default defineConfig({ testDir: "./e2e", testMatch: /(?:legislator-profiles|dashboard-cards|recommendations|integration-seams)\.spec\.ts/, workers: 1, retries: 0, use: { baseURL: "http://127.0.0.1:13302", trace: "retain-on-failure" }, projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }] });
