import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  testMatch: "dashboard-cards.spec.ts",
  workers: 1,
  use: { baseURL: "http://127.0.0.1:13280", trace: "retain-on-failure" },
  projects: [{ name: "dashboard-chromium", use: { ...devices["Desktop Chrome"] } }],
});
