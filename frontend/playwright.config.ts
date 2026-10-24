import { defineConfig, devices } from "@playwright/test";

const UV = "C:\\Users\\Aryan\\AppData\\Roaming\\Python\\Python314\\Scripts\\uv.exe";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // Real FastAPI sidecar so every E2E run exercises the true
      // frontend <-> backend contract (auth, runs, SSE, providers).
      command: `"${UV}" run --project backend uvicorn symbiot.sidecar:app --app-dir backend/src --host 127.0.0.1 --port 8100`,
      url: "http://127.0.0.1:8100/health",
      reuseExistingServer: true,
      timeout: 180_000,
      cwd: "..",
    },
    {
      command: "pnpm exec vite --port 5173 --strictPort",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
