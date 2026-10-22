import { defineConfig, devices } from "@playwright/test";

const python = process.env.RESEARCH_TEST_PYTHON ?? "../../legislation-tracker-changelog-partitions/legislation-tracker-backend/.venv/bin/python";
export default defineConfig({
  testDir: "./e2e", testMatch: "representative-research.spec.ts", workers: 1, retries: 0,
  use: { baseURL: "http://127.0.0.1:13420", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    { command: `rtk run "cd ../legislation-tracker-backend && rtk proxy ${python} scripts/research-e2e-server.py"`, url: "http://127.0.0.1:18420/api/topics/", reuseExistingServer: false, timeout: 60000 },
    { command: "rtk proxy pnpm exec next dev --hostname 127.0.0.1 --port 13420", env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:18420", E2E_RESEARCH_BUILD: "1" }, url: "http://127.0.0.1:13420", reuseExistingServer: false, timeout: 60000 },
  ],
});
