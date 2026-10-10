import { defineConfig, devices } from "@playwright/test";

const apiPort = process.env.E2E_API_PORT ?? "18000";
const clientPort = process.env.E2E_CLIENT_PORT ?? "13100";
for (const port of [apiPort, clientPort]) {
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    throw new Error("E2E ports must be integers between 1 and 65535");
  }
}
const apiURL = `http://127.0.0.1:${apiPort}`;
const clientURL = `http://127.0.0.1:${clientPort}`;
process.env.E2E_API_URL = apiURL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  use: {
    baseURL: clientURL,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command:
        "cd ../legislation-tracker-backend && bash scripts/start-e2e-api.sh",
      env: { ...process.env, E2E_API_PORT: apiPort, E2E_CLIENT_ORIGIN: clientURL },
      url: `${apiURL}/api/topics/`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port ${clientPort}`,
      url: clientURL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        NEXT_PUBLIC_API_URL: apiURL,
      },
    },
  ],
});
