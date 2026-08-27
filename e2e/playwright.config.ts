import path from "node:path";
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:18099",
    trace: "on-first-retry",
  },
  projects: [
    { name: "sidecar", testIgnore: /grist-widget/ },
    {
      name: "grist",
      testMatch: /grist-widget/,
      use: { baseURL: "http://127.0.0.1:18080", viewport: { width: 1400, height: 900 } },
    },
  ],
  webServer: {
    command:
      "SIH_E2E=1 SIH_REQUIRE_ROLES=true SIH_MANAGERS=boss@hku.hk SIH_MAINTAINERS=keeper@hku.hk SIH_SECRET_KEY=k-k-k-k-k-k-k-k-k-k-k-k-32chars SIH_AUTH_ALLOWED_EMAIL_DOMAINS=hku.hk OPENROUTER_STUB=ask .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18099",
    cwd: path.join(__dirname, "../sidecar"),
    url: "http://127.0.0.1:18099/docs",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
