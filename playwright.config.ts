import { defineConfig, devices } from '@playwright/test';

// Smoke-test config — Chromium only, 4 core flows from e2e/.
// Run: `npx playwright test`. CI sets PW_CI=1 so we don't reuse a stale server.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      // Local: use the project venv's uvicorn. CI: backend deps installed to
      // system python, so `python -m uvicorn` resolves the same module.
      command: process.env.CI
        ? 'python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000'
        : './venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000',
      port: 8000,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: 'npm run dev',
      port: 3000,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
