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

test('对话输入框正常初始化，打开命令面板可加载知识库', async ({ page, api }) => {
  await api.signIn()
  bootWorkspace(api)
  const vueErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error' && message.text().startsWith('[Nexus] Unhandled Vue error:')) {
      vueErrors.push(message.text())
    }
  })

  const knowledgeBasesPath = '/api/v1/tenants/a/knowledge/bases'
  const waitForKnowledgeBases = () => page.waitForResponse(
    response => new URL(response.url()).pathname === knowledgeBasesPath && response.ok(),
  )
  await Promise.all([waitForKnowledgeBases(), page.goto('/')])
  await expect(page.getByTestId('chat-composer').locator('textarea')).toBeVisible()

  await Promise.all([
    waitForKnowledgeBases(),
    page.keyboard.press('Control+k'),
  ])
  await expect(page.locator('.cmdk__input')).toBeVisible()
  expect(vueErrors).toEqual([])
})

test('打开知识库详情只加载一次文档列表并保留当前页面实例', async ({ page, api }) => {
  await api.signIn()
  bootWorkspace(api)
  const path = '/api/v1/tenants/a/knowledge'
  const detail = `${path}/bases/kb`
  const base = { id: 'kb', tenant_id: 'a', name: '运行手册', type: 'document', storage_backend_id: 'local' }
  api.handle(request => {
    const url = new URL(request.url()).pathname
    if (url === `${path}/bases`) return { body: { items: [base] } }
    if (url === detail) return { body: base }
    if (url === `${detail}/documents`) {
      return { body: {
        total: 1,
        items: [{ id: 'doc', kb_id: 'kb', filename: 'ready.pdf', file_type: 'pdf', latest_version: { state: 'ready' } }],
      } }
    }
    if (url === `${detail}/folders`) return { body: { folders: [], total_document_count: 1 } }
    if (url === `${detail}/tags`) return { body: { items: [], total: 0 } }
    if (url === `${path}/parser-engines`) return { body: { data: [] } }
  })

  await page.goto('/platform/knowledge-bases')
  const timeOrigin = await page.evaluate(() => performance.timeOrigin)
  await page.locator('.kb-directory .resource-directory-card').filter({ hasText: base.name }).locator('button').click()
  await expect(page).toHaveURL(/\/platform\/knowledge-bases\/kb$/)
  await expect(page.locator('.doc-card-area').getByText('ready', { exact: true }).first()).toBeVisible()
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin)
  expect(api.requests.filter(request => request === `GET ${detail}/documents`)).toHaveLength(1)
})

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


test('会话通过顶部标签查看对话、轨迹和产物，产物加载失败可以重试', async ({ page, api }) => {
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
  const tabs = page.getByRole('tablist')
  await expect(tabs.getByRole('tab')).toHaveCount(3)
  await expect(tabs.getByRole('tab', { name: '对话' })).toHaveAttribute('aria-selected', 'true')
  await tabs.getByRole('tab', { name: '产物' }).click()
  await expect(page.locator('#chat-panel-artifacts')).toContainText('产物加载失败')
  fail = false
  await page.locator('#chat-panel-artifacts').getByRole('button', { name: '重试' }).click()
  await expect(page.locator('#chat-panel-artifacts')).toContainText('report.txt')
  await tabs.getByRole('tab', { name: '轨迹' }).click()
  await expect(page.locator('#chat-panel-trajectory')).toBeVisible()
  await page.goto('/platform/chat/s2')
  await page.getByRole('tab', { name: '产物' }).click()
  await expect(page.locator('#chat-panel-artifacts')).toContainText('当前会话暂无产物')
  await expect(page.locator('#chat-panel-artifacts')).not.toContainText('report.txt')
  await expectResponsive(page)
  await expect.poll(async () => (await page.locator('.platform-route-outlet').boundingBox())!.width >= 300).toBe(true)
})

test('会话页顶部只显示左对齐的对话、轨迹和产物标签', async ({ page, api }) => {
  test.setTimeout(120_000)
  await api.signIn(); bootWorkspace(api)
  const messages = [
    { id: 'm1', run_id: 'r1', sequence: 1, role: 'user', content: '部署流程已完成', created_at: '2026-11-27T00:00:00Z' },
    { id: 'm2', run_id: 'r1', sequence: 2, role: 'assistant', content: '正在检查部署条件', created_at: '2026-11-27T00:00:01Z' },
    { id: 'm3', run_id: 'r1', sequence: 3, role: 'tool', tool_call_id: 'call1', content: '部署环境检查通过', created_at: '2026-11-27T00:00:02Z' },
    { id: 'm4', run_id: 'r1', sequence: 4, role: 'assistant', content: '部署步骤已核验', created_at: '2026-11-27T00:00:03Z' },
  ]
  const completedRun = { id: 'r1', tenant_id: 'a', session_id: 's1', principal_id: 'u', status: 'completed',
    attempt: 1, error_code: null, error_message: null, created_at: '2026-11-27T00:00:00Z',
    started_at: '2026-11-27T00:00:00Z', ended_at: '2026-11-27T00:00:01Z', queue_position: null, attention_required: false }
  api.handle(request => {
    const url = new URL(request.url()), path = url.pathname
    if (path === '/api/v1/tenants/a/agents') return { body: [{ id: 'agent', name: 'Agent', description: '', status: 'published',
      published_version_id: 'av1', resource_bindings: [] }] }
    if (path === '/api/v1/tenants/a/sessions') return { body: [{ id: 's1', agent_version_id: 'av1', title: '部署流程' }] }
    if (path === '/api/v1/tenants/a/sessions/s1/messages') return { body: { messages, latest_run: completedRun, blocked: null } }
    if (path === '/api/v1/tenants/a/native/sessions/s1/tool-grants') return { body: [] }
    if (path === '/api/v1/tenants/a/sessions') return { body: [{ id: 's1', agent_version_id: 'av1', title: '部署流程' }] }
    if (path === '/api/v1/tenants/a/runs/r1/trajectory') return { body: [
      { id: 'tr1', run_id: 'r1', sequence: 1, turn: 1, attempt: 1, purpose: 'assistant', status: 'completed',
        input_estimate_tokens: 128, run_total_tokens: 160, request_snapshot: { messages: [{ role: 'user', content: '部署流程已完成' }],
          tools: [{ name: 'deploy', description: '部署应用', parameters: { type: 'object' } }] },
        response_snapshot: { text: '正在检查部署条件', tool_calls: [{ id: 'call1', name: 'deploy', arguments: '{"target":"production"}' }] },
        usage: { input: 130, output: 30, cache_read: 50 }, error_code: null,
        started_at: '2026-11-27T00:00:00Z', completed_at: '2026-11-27T00:00:01Z' },
      { id: 'tr2', run_id: 'r1', sequence: 2, turn: 2, attempt: 1, purpose: 'assistant', status: 'completed',
        input_estimate_tokens: 210, run_total_tokens: 260, request_snapshot: { messages: [{ role: 'tool', content: '部署环境检查通过' }], tools: [] },
        response_snapshot: { text: '部署步骤已核验', tool_calls: [] }, usage: { input: 120, output: 30, cache_read: 40 }, error_code: null,
        started_at: '2026-11-27T00:00:02Z', completed_at: '2026-11-27T00:00:03Z' },
    ] }
    if (path === '/api/v1/tenants/a/artifacts') return { body: { items: [] } }
  })
  await page.goto('/platform/chat/s1')
  await expect(page.locator('.chat-topbar')).toBeVisible({ timeout: 60_000 })
  const topbar = page.locator('.chat-topbar')
  await expect(topbar.getByRole('tab')).toHaveCount(3)
  await expect(topbar.getByRole('tab').nth(0)).toHaveText('对话')
  await expect(topbar.getByRole('tab').nth(2)).toHaveText('产物')
  await expect(topbar.locator('> :not(nav)')).toHaveCount(0)
  const topbarBox = await topbar.boundingBox(), tabsBox = await topbar.getByRole('tablist').boundingBox()
  expect(topbarBox && tabsBox && tabsBox.x - topbarBox.x).toBeLessThanOrEqual(24)
  await expect(topbar.getByRole('tab', { name: '对话' })).toHaveAttribute('aria-selected', 'true')
  await topbar.getByRole('tab', { name: '对话' }).press('ArrowRight')
  await expect(topbar.getByRole('tab', { name: '轨迹' })).toHaveAttribute('aria-selected', 'true')
  await topbar.getByRole('tab', { name: '轨迹' }).click()
  await expect(page.locator('#chat-panel-trajectory')).toContainText('部署步骤已核验')
  const trajectory = page.locator('#chat-panel-trajectory')
  await expect(trajectory.getByRole('row')).toHaveCount(6)
  await expect(trajectory.getByRole('row').nth(1)).toContainText('Run 1')
  await expect(trajectory.getByRole('columnheader').nth(2)).toHaveText('Token')
  await expect(trajectory).toContainText('命中缓存')
  await expect(trajectory).toContainText('90')
  await trajectory.getByRole('row').filter({ hasText: 'deploy' }).click()
  await expect(page.getByTestId('trajectory-inspector')).toContainText('production')
  await expect(page.getByTestId('trajectory-inspector')).toContainText('部署环境检查通过')
  await trajectory.getByRole('row').filter({ hasText: '部署步骤已核验' }).click()
  await expect(page.getByTestId('trajectory-inspector')).toContainText('部署步骤已核验')
  await expect(trajectory.getByRole('row').filter({ hasText: '部署步骤已核验' })).toContainText('实际')
  await expect(page.getByTestId('chat-learn-skill')).toHaveCount(0)
})

test('员工知识库新建目录并将所选文件上传到当前目录', async ({ page, api }) => {
  page.setDefaultTimeout(15000)
  await api.signIn()
  bootWorkspace(api)
  const root = '/api/v1/tenants/a/knowledge', kb = root + '/bases/kb'
  const base = { id: 'kb', tenant_id: 'a', name: '运行手册', type: 'document', can_edit: true,
    created_by: 'u', storage_backend_id: 'local', indexing_strategy: { vector: false, keyword: true } }
  let created = '', uploaded = false
  const doc = { id: 'doc', kb_id: 'kb', filename: 'manual.txt', folder_path: '手册',
    file_type: 'txt', latest_version: { state: 'ready' } }
  api.handle(request => {
    const url = new URL(request.url())
    if (url.pathname === '/api/v1/system/info') return { body: { data: {} } }
    if (url.pathname === kb) return { body: base }
    if (url.pathname === root + '/bases') return { body: { items: [base] } }
    if (url.pathname === kb + '/folders') {
      if (request.method() === 'POST') {
        created = request.postDataJSON().path
        return { status: 201, body: { path: created } }
      }
      return { body: { root_document_count: 0, total_document_count: Number(uploaded),
        folders: created ? [{ path: created, name: created, total_count: Number(uploaded),
          document_count: Number(uploaded), children: [] }] : [] } }
    }
    if (url.pathname === kb + '/documents') {
      if (request.method() === 'POST') {
        expect(request.postData()).toContain('手册/manual.txt')
        uploaded = true
        return { status: 201, body: { document: doc, deduplicated: false } }
      }
      return { body: uploaded && url.searchParams.get('folder_path') === '手册' ? { items: [doc], total: 1 } : { items: [], total: 0 } }
    }
    if (url.pathname === kb + '/tags') return { body: { items: [], total: 0 } }
    if (url.pathname === root + '/documents/doc') return { body: doc }
    if (url.pathname === root + '/parser-engines') return { body: { data: [] } }
  })
  await page.goto('/platform/knowledge-bases/kb')
  const tree = page.locator('.kb-folder-tree')
  await tree.getByRole('button', { name: '新建子目录' }).click()
  const dialog = page.locator('.t-dialog:visible')
  await dialog.getByRole('textbox').fill('手册')
  await dialog.getByRole('button', { name: '创建', exact: true }).click()
  await expect(tree.locator('.kb-folder-row.active')).toContainText('手册')
  await page.locator('.doc-filter-actions input[type="file"]:not([webkitdirectory])').setInputFiles({
    name: 'manual.txt', mimeType: 'text/plain', buffer: Buffer.from('manual'),
  })
  const upload = page.locator('.upload-confirm-modal')
  await expect(upload).toContainText('手册')
  await upload.getByRole('button', { name: '确认上传并解析' }).click()
  await expect.poll(() => uploaded).toBe(true)
  await expect(page.locator('.doc-card-area').getByText('manual', { exact: true }).first()).toBeVisible()
  await expect(page.locator('.doc-list-view').getByRole('button', { name: 'manual', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '卡片视图', exact: true }).click()
  await expect(page.locator('.doc-card-view').getByRole('button', { name: 'manual', exact: true })).toBeVisible()
})
