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
  await expect(link).toHaveAttribute('href', process.env.NEXUS_E2E_PREVIEW === '1' ? '/admin/parsers' : 'http://127.0.0.1:5174/admin/parsers')
  await expect(page).toHaveURL(/5193\/platform\/settings\?section=parser$/)
  expect(api.requests.some(path => /parser-engine|\/admin\//.test(path))).toBe(false)
  await expectResponsive(page)
})


function bootWorkspace(api: import('./fixtures').ApiMock) {
  api.handle(request => {
    const path = new URL(request.url()).pathname
    const boot: Record<string, unknown> = {
      '/api/v1/tenants/a/knowledge/bases': { items: [] },
      '/api/v1/tenants/a/knowledge/shared-bases': { items: [] },
      '/api/v1/tenants/a/agents': [], '/api/v1/agents': { data: [] },
      '/api/v1/shared-agents': { success: true, data: [] },
      '/api/v1/tenants/a/model-settings': { providers: [], defaults: {}, can_manage_tenant: true },
      '/api/v1/web-search-providers': { data: [] }, '/api/v1/tenants/a/sessions': [],
      '/api/v1/shared-spaces': [],
      '/api/v1/me/invitations/pending-count': { count: 0 },
    }
    if (request.method() === 'GET' && path in boot) return { body: boot[path] }
    if (path === '/api/v1/system/capabilities') return { body: { data: { capabilities: { agents: { supported: true } }, edition: 'community' } } }
  })
}

test('员工主菜单仅三项，设置弹出且账户仅三项，旧工具地址不加载管理能力', async ({ page, api }) => {
  await api.signIn(); bootWorkspace(api)
  await page.goto('/platform/knowledge-bases')
  await expect(page.locator('[data-guide^="nav-"]')).toHaveCount(3)
  await expect(page.getByRole('button', { name: /创建.*知识库/ })).toHaveCount(0)
  await page.locator('.user-button').click()
  await page.locator('.user-dropdown .menu-item').filter({ hasText: '设置' }).click()
  await expect(page.locator('.settings-modal-shell')).toBeVisible()
  await expect(page.locator('.workspace-account-settings > .settings-modal')).toHaveCSS('max-width', '1280px')
  await expect(page.locator('.workspace-account-settings .content-wrapper')).toHaveCSS('padding-left', '48px')
  await expect(page.locator('.settings-modal-shell')).not.toHaveClass(/settings-page/)
  await expect(page.locator('.settings-nav .nav-item')).toHaveCount(3)
  await expect(page.locator('.settings-nav .nav-group-title')).toHaveText(['账户'])
  await expect(page).toHaveURL(/knowledge-bases$/)
  await expectResponsive(page)
  await page.keyboard.press('Escape')
  await expect(page.locator('.settings-modal-shell')).toHaveCount(0)
  await page.goto('/platform/toolbox/mcp')
  await expect(page).toHaveURL(/creatChat$/)
  expect(api.requests.some(path => /mcp-services|memory-settings|skills/.test(path))).toBe(false)
})


test('会话产物在右侧折叠，失败可以重试，切换会话清除旧产物', async ({ page, api }) => {
  await api.signIn(); bootWorkspace(api)
  let fail = true
  api.handle(request => {
    const url = new URL(request.url()), path = url.pathname
    if (path === '/api/v1/tenants/a/agents') return { body: [] }
    if (/\/sessions\/s[12]\/messages$/.test(path)) return { body: { messages: [], latest_run: null, blocked: null } }
    if (/\/native\/sessions\/s[12]\/tool-grants$/.test(path)) return { body: [] }
    if (path === '/api/v1/tenants/a/artifacts') {
      if (fail) return { status: 503, body: { error: 'temporarily_unavailable' } }
      return { body: { items: url.searchParams.get('session_id') === 's1' ? [{ id: 'f1', name: 'report.txt', session_id: 's1', run_id: 'r1', size: 10, created_at: '2026-11-18T00:00:00Z' }] : [] } }
    }
  })
  await page.goto('/platform/chat/s1')
  await page.getByRole('button', { name: '会话产物', exact: true }).click()
  await expect(page.locator('#session-artifacts')).toContainText('产物加载失败')
  fail = false
  await page.locator('#session-artifacts').getByRole('button', { name: '重试' }).click()
  await expect(page.locator('#session-artifacts')).toContainText('report.txt')
  await page.getByRole('button', { name: '会话产物', exact: true }).click()
  await expect(page.locator('#session-artifacts')).toHaveCount(0)
  await page.goto('/platform/chat/s2')
  await page.getByRole('button', { name: '会话产物', exact: true }).click()
  await expect(page.locator('#session-artifacts')).toContainText('当前会话暂无产物')
  await expect(page.locator('#session-artifacts')).not.toContainText('report.txt')
  await expectResponsive(page)
  await expect.poll(async () => (await page.locator('.platform-route-outlet').boundingBox())!.width >= 300).toBe(true)
})
