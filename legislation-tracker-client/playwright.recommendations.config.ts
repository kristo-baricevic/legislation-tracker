import { defineConfig, devices } from "@playwright/test";
const port = Number(process.env.RECOMMENDATIONS_CLIENT_PORT);
if (!Number.isInteger(port) || port < 1024 || port === 13280) throw new Error("Set RECOMMENDATIONS_CLIENT_PORT to a discovered isolated port");
export default defineConfig({
  testDir: "./e2e", testMatch: "recommendations.spec.ts", fullyParallel: false,
  retries: 0, workers: 1,
  use: { baseURL: `http://127.0.0.1:${port}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `rtk proxy node_modules/.bin/next dev --hostname 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}`, reuseExistingServer: false, timeout: 120000,
    env: { ...process.env, NEXT_PUBLIC_API_URL: `http://127.0.0.1:${port}` },
  },
});
