import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: "http://127.0.0.1:13100",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command:
        "cd ../legislation-tracker-backend && E2E_API_PORT=18000 E2E_CLIENT_ORIGIN=http://127.0.0.1:13100 bash scripts/start-e2e-api.sh",
      url: "http://127.0.0.1:18000/api/topics/",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "pnpm exec next dev --hostname 127.0.0.1 --port 13100",
      url: "http://127.0.0.1:13100",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        NEXT_PUBLIC_API_URL: "http://127.0.0.1:18000",
      },
    },
  ],
});
