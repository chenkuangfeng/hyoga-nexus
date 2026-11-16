/** 双应用真实界面回归；API 由用例显式模拟，生产产物与真实服务另行验收。 */
import { defineConfig, devices } from '@playwright/test'

const preview = process.env.NEXUS_E2E_PREVIEW === '1'
const app = process.env.NEXUS_E2E_APP
const serverEnv = { GOMEMLIMIT: process.env.GOMEMLIMIT || '192MiB', GOMAXPROCS: process.env.GOMAXPROCS || '2' }
const reportApp = `${preview ? 'preview-' : ''}${app || 'all'}`
const chromiumPath = process.env.NEXUS_E2E_CHROMIUM_PATH
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  outputDir: `test-results/${reportApp}`,
  reporter: [['list'], ['html', { open: 'never', outputFolder: `playwright-report/${reportApp}` }]],
  use: {
    ...devices['Desktop Chrome'],
    locale: 'zh-CN',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: chromiumPath ? { executablePath: chromiumPath } : {},
  },
  projects: [
    { name: 'workspace', testMatch: preview ? ['workspace.spec.ts', 'workspace-preview.spec.ts'] : 'workspace.spec.ts', use: { baseURL: 'http://127.0.0.1:5193' } },
    { name: 'admin', testMatch: 'admin.spec.ts', use: { baseURL: 'http://127.0.0.1:5194/admin/' } },
  ],
  webServer: [
    { command: preview ? 'corepack pnpm --filter @nexus-web/workspace exec vite preview --host 127.0.0.1 --port 5193 --strictPort' : 'corepack pnpm exec vite --config e2e/vite.config.ts --host 127.0.0.1 --port 5193 --strictPort', url: 'http://127.0.0.1:5193/login', reuseExistingServer: false, env: { ...serverEnv, NEXUS_E2E_APP: 'workspace' }, timeout: 90_000 },
    { command: preview ? 'corepack pnpm --filter @nexus-web/admin exec vite preview --host 127.0.0.1 --port 5194 --strictPort' : 'corepack pnpm exec vite --config e2e/vite.config.ts --host 127.0.0.1 --port 5194 --strictPort', url: 'http://127.0.0.1:5194/admin/login', reuseExistingServer: false, env: { ...serverEnv, NEXUS_E2E_APP: 'admin' }, timeout: 90_000 },
  ].filter((_, index) => !app || (app === 'workspace' ? index === 0 : index === 1)),
})
