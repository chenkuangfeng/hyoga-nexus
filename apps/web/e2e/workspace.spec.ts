import { test, expect, expectResponsive } from './fixtures'

test('员工应用登录入口独立且可在手机宽度使用', async ({ page }) => {
  await page.goto('/login')
  await expect(page.locator('input[type="password"]')).toBeVisible()
  await expect(page).toHaveURL(/5193\/login$/)
  await expectResponsive(page)
})

test('旧解析书签只显示显式管理链接，不读取治理配置', async ({ page, api }) => {
  await api.signIn()
  const boot: Record<string, unknown> = {
    '/api/v1/tenants/a/knowledge/bases': { items: [] },
    '/api/v1/tenants/a/knowledge/shared-bases': { items: [] },
    '/api/v1/agents': { data: [] },
    '/api/v1/shared-agents': { success: true, data: [] },
    '/api/v1/tenants/a/model-settings': { providers: [], defaults: {}, can_manage_tenant: true },
    '/api/v1/web-search-providers': { data: [] },
    '/api/v1/shared-spaces': [],
    '/api/v1/tenants/a/sessions': [],
    '/api/v1/me/invitations/pending-count': { count: 0 },
  }
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (request.method() === 'GET' && Object.hasOwn(boot, path)) return { body: boot[path] }
    if (request.method() === 'GET' && new URL(request.url()).pathname === '/api/v1/system/capabilities') return { body: { data: { capabilities: {}, edition: 'community' } } }
  })
  await page.goto('/platform/settings?section=parser')
  const link = page.locator('a[href$="/admin/parsers"]')
  await expect(link).toBeVisible()
  await expect(link).toHaveAttribute('href', 'http://127.0.0.1:5174/admin/parsers')
  await expect(page).toHaveURL(/5193\/platform\/settings\?section=parser$/)
  expect(api.requests.some(path => /parser-engine|\/admin\//.test(path))).toBe(false)
  await expectResponsive(page)
})
