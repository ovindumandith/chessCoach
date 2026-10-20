import { defineConfig } from "@playwright/test";

// End-to-end tests run against a full running stack (docker compose up), which includes
// the real Stockfish worker. See README "End-to-end tests".
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    // Uses the system Chrome by default; set PW_CHANNEL=chromium for Playwright's own build.
    channel: process.env.PW_CHANNEL === "chromium" ? undefined : (process.env.PW_CHANNEL ?? "chrome"),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
