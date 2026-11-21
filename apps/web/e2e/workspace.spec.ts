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
  const link = page.locator('a[href$="/enterprise/parsers"]')
  await expect(link).toBeVisible()
  await expect(link).toHaveAttribute('href', '/enterprise/parsers')
  await expect(link).toHaveAttribute('target', '_blank')
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

test('数据库重建后清理旧空间缓存并重新完成开发登录', async ({ page, api }) => {
  bootWorkspace(api)
  const oldSpace = '09844aa5-952c-49e6-b97b-3adc37bbec05'
  await page.addInitScript(spaceId => {
    localStorage.setItem('weknora_user', JSON.stringify({ id: 'old-user', username: 'Owner' }))
    localStorage.setItem('weknora_tenant', JSON.stringify({ id: spaceId, name: 'Acme' }))
    localStorage.setItem('weknora_token', 'old-token')
    localStorage.setItem('weknora_selected_tenant_id', spaceId)
  }, oldSpace)

  let staleLookups = 0
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/auth/me' && request.headers()['x-tenant-id'] === oldSpace) {
      staleLookups++
      return { status: 404, body: { error: { code: 'not_found', message: 'Tenant not found' } } }
    }
    if (path === '/api/v1/auth/config') {
      return { body: { success: true, development_login: true } }
    }
    if (path === '/api/v1/auth/dev-session') {
      expect(request.headers()['x-tenant-id']).toBeUndefined()
      expect(request.headers().authorization).toBeUndefined()
      const tenant = { id: 'a', name: 'Acme' }
      return { body: {
        success: true, token: 'new-token', tenant, active_tenant: tenant,
        user: { id: 'u', username: 'Owner', email: 'owner@example.test', tenant_id: 'a' },
        memberships: [{ tenant_id: 'a', tenant_name: 'Acme', role: 'owner', entries: ['workspace'] }],
      } }
    }
  })

  await page.goto('/platform/knowledge-bases')
  await expect(page.locator('[data-guide^="nav-"]')).toHaveCount(3)
  await expect(page).toHaveURL(/knowledge-bases$/)
  expect(staleLookups).toBe(1)
  expect(await page.evaluate(() => localStorage.getItem('weknora_selected_tenant_id'))).toBe('a')
})

test('企业 owner 在新标签页打开企业管理并沿用工作台会话', async ({ page, api, context }) => {
  bootWorkspace(api)
  await page.addInitScript(() => {
    if (location.pathname !== '/platform/knowledge-bases') return
    localStorage.setItem('weknora_token', 'workspace-session')
    localStorage.setItem('weknora_selected_tenant_id', 'a')
  })
  await page.goto('/platform/knowledge-bases')
  await page.locator('.user-button').click()
  const link = page.getByRole('link', { name: '企业管理', exact: true })
  await expect(link).toHaveAttribute('href', '/enterprise/')
  await expect(link.locator('xpath=preceding-sibling::*[1]')).toHaveText('设置')
  await link.focus()
  const [enterprisePage, request] = await Promise.all([
    context.waitForEvent('page'),
    context.waitForEvent('request', {
      predicate: request => new URL(request.url()).pathname === '/api/v1/auth/me' && request.frame().page() !== page,
    }),
    link.press('Enter'),
  ])
  expect(request.headers().authorization).toBe('Bearer workspace-session')
  expect(request.headers()['x-tenant-id']).toBe('a')
  await expect(enterprisePage).toHaveURL(/5193\/enterprise\/settings$/)
  await expect(enterprisePage.locator('#enterprise-navigation')).toBeVisible()
  await expect(page).toHaveURL(/5193\/platform\/knowledge-bases$/)
  await expect(page.locator('[data-guide^="nav-"]')).toHaveCount(3)
  expect(api.requests).not.toContain('POST /api/v1/auth/login')
})

test('展开和折叠侧栏时，员工工作台的当前和未选中菜单均显示图标', async ({ page, api }) => {
  await api.signIn()
  bootWorkspace(api)
  await page.goto('/platform/knowledge-bases')
  const sidebar = page.locator('.aside_box')
  const imageLoaded = async (path: string) => {
    const icon = sidebar.locator(`[data-guide="nav-${path}"] img.icon`)
    await expect(icon).toBeVisible()
    await expect.poll(() => icon.evaluate(el => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  }
  await imageLoaded('agents')
  await imageLoaded('creatChat')
  await expect(sidebar.locator('[data-guide="nav-knowledge-bases"] .icon--brand')).toHaveCSS('mask-image', /url\(/)

  await sidebar.locator('.sidebar-toggle').click()
  await expect(sidebar).toHaveClass(/aside_box--collapsed/)
  await sidebar.locator('[data-guide="nav-creatChat"]').press('Enter')
  await expect(page).toHaveURL(/\/platform\/creatChat$/)
  await imageLoaded('knowledge-bases')
  await imageLoaded('agents')
  await expect(sidebar.locator('[data-guide="nav-creatChat"] .icon--brand')).toHaveCSS('mask-image', /url\(/)
})

test('普通成员看不到企业管理入口且直达页面显示无权限', async ({ page, api }) => {
  await api.signIn(['workspace'])
  bootWorkspace(api)
  await page.goto('/platform/knowledge-bases')
  await page.locator('.user-button').click()
  await expect(page.getByRole('link', { name: '企业管理', exact: true })).toHaveCount(0)
  await page.goto('/enterprise/')
  await expect(page.getByText('无权访问企业管理后台', { exact: true })).toBeVisible()
  expect(api.requests).not.toContain('GET /api/v1/tenants/a/me/permissions')
})

test('员工主菜单仅三项，设置弹出且个人设置仅三项，旧工具地址不加载管理能力', async ({ page, api }) => {
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
