import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { test, expect, expectResponsive } from './fixtures'

test('管理应用登录入口独立且可在手机宽度使用', async ({ page }) => {
  await page.goto('login')
  await expect(page.locator('input[type="password"]')).toBeVisible()
  await expect(page).toHaveURL(/\/enterprise\/login$/)
  await expectResponsive(page)
})

test('解析配置确认后保存，保留既有密钥与关闭状态', async ({ page, api }) => {
  await api.signIn()
  let config: Record<string, unknown> = { mineru_api_key: '******', mineru_endpoint: 'https://mineru.example.test', mineru_enable_table: false }
  const writes: Record<string, unknown>[] = []
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (['GET', 'PUT'].includes(request.method()) && path === '/api/v1/tenants/a/admin/knowledge/parser-engine-config') {
      if (request.method() === 'PUT') {
        const input = request.postDataJSON() as Record<string, unknown>
        writes.push(input); config = { ...input, mineru_api_key: '******' }
      }
      return { body: { data: config } }
    }
    if (request.method() === 'GET' && path === '/api/v1/tenants/a/admin/knowledge/parser-engines') return { body: { data: [{ Name: 'mineru', Description: 'MinerU', FileTypes: ['pdf'], Available: true, UnavailableReason: '' }] } }
  })
  await page.goto('parsers')
  await expect(page.locator('.engine-card')).toHaveCount(4)
  await expect(page.locator('#enterprise-navigation').getByRole('link', { name: '解析引擎' })).toHaveClass(/\bactive\b/)
  await page.locator('.engine-card').first().click()
  await expect(page.locator('.setting-drawer')).toBeVisible()
  await expect(page.locator('.parser-group')).toHaveCount(1)
  for (const input of await page.locator('input[type="password"]').all()) await expect(input).toHaveValue('')
  const endpoint = page.locator('.parser-group').first().locator('input').first()
  await endpoint.fill('https://updated.example.test'); await endpoint.blur()
  await page.locator('.setting-drawer__footer-right button').last().click()
  await expect(page.locator('.t-dialog:visible').last()).toBeVisible(); expect(writes).toHaveLength(0)
  await page.locator('.t-dialog__footer button').last().click()
  await expect(page.locator('.setting-drawer .t-alert--success')).toBeVisible()
  expect(writes).toEqual([{ mineru_api_key: '******', mineru_endpoint: 'https://updated.example.test', mineru_enable_table: false }])
  await expectResponsive(page)
})

test('WeKnora 分组下的链接直接可用，图标侧栏保留键盘访问', async ({ page, api }, testInfo) => {
  await api.signIn()
  api.handle(request => new URL(request.url()).pathname === '/api/v1/tenants/a/me/permissions'
    ? { body: { apis: ['org:manage', 'members:manage', 'roles:manage', 'models:manage', 'tools:manage', 'enterprise_kbs:manage', 'enterprise_agents:manage', 'audit:read', 'policy:manage'] } } : undefined)
  await page.goto('')
  const navigation = page.locator('#enterprise-navigation')
  await expect(navigation.locator('.nav-group-title')).toHaveText(['配置', '空间', '发布集成', '数据与扩展', '权限', '系统'])
  const expected = [
    ['模型', '知识库', '工具', '智能体'], ['企业空间', '企业策略'], ['MCP服务', 'IM 集成'],
    ['向量引擎', '解析引擎', '存储引擎', '沙箱引擎', '知识图谱'],
    ['企业组织', '用户', '角色'], ['系统设置', '运行状况', '审计日志'],
  ]
  for (const [index, links] of expected.entries()) {
    await expect(navigation.locator('.nav-group').nth(index).getByRole('link')).toHaveText(links)
  }
  const settings = navigation.getByRole('link', { name: '系统设置', exact: true })
  await expect(settings).toHaveClass(/\bactive\b/)
  await page.screenshot({ path: testInfo.outputPath('grouped-navigation.png') })
  await page.getByRole('button', { name: '收起侧边栏' }).click()
  const parser = navigation.getByRole('link', { name: '解析引擎' })
  await expect(parser).toHaveAttribute('title', '解析引擎')
  await parser.focus()
  await expect(parser).toBeFocused()
  await expectResponsive(page)
  await expect(parser).toBeVisible()
  await page.reload()
  await expect(parser).toBeVisible()
})

test('切换管理菜单时保留侧栏，只在右侧切换路由', async ({ page, api }) => {
  await api.signIn()
  const permissionsPath = '/api/v1/tenants/a/me/permissions'
  let releasePermissions = () => {}
  const pendingPermissions = new Promise<void>(resolve => { releasePermissions = resolve })
  let delayPermissions = false
  api.handle(async request => {
    const path = new URL(request.url()).pathname
    if (path === permissionsPath) {
      if (delayPermissions) await pendingPermissions
      return { body: { apis: ['enterprise_kbs:manage'] } }
    }
    if (path === '/api/v1/tenants/a/admin/knowledge/storage-backends') return { body: { items: [] } }
  })
  await page.goto('settings')
  const navigation = page.locator('#enterprise-navigation')
  const storageLink = navigation.locator('a[href$="/storage"]')
  await storageLink.evaluate(element => element.setAttribute('data-e2e-original', 'true'))
  delayPermissions = true
  const permissionRequest = page.waitForRequest(request => new URL(request.url()).pathname === permissionsPath)
  try {
    await storageLink.focus()
    await page.keyboard.press('Enter')
    await permissionRequest
    await expect(storageLink).toBeFocused()
    await expect(page).toHaveURL(/\/enterprise\/settings$/)
  } finally {
    releasePermissions()
  }
  await expect(page).toHaveURL(/\/enterprise\/storage$/)
  await expect(page.locator('.backend-card--add')).toBeVisible()
  await expect(storageLink).toHaveAttribute('data-e2e-original', 'true')
  await expect(storageLink).toHaveClass(/\bactive\b/)
  await page.goBack()
  await expect(page).toHaveURL(/\/enterprise\/settings$/)
  await expect(storageLink).toHaveAttribute('data-e2e-original', 'true')
  await expect(storageLink).toBeVisible()
})

test('存储与向量库使用原版卡片和抽屉，保留创建及键盘编辑流程', async ({ page, api }) => {
  await api.signIn()
  const storage: Record<string, unknown>[] = []
  const vectors = [{ id: 'v1', name: 'Qdrant', engine: 'qdrant', builtin: false, connection_config: {}, index_config: {} }]
  const writes: Record<string, unknown>[] = []
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/admin/knowledge/storage-backends') {
      if (request.method() === 'POST') {
        const row = { id: 's1', builtin: false, ...request.postDataJSON() as Record<string, unknown> }; storage.push(row); return { body: row }
      }
      return { body: { items: storage } }
    }
    if (path === '/api/v1/tenants/a/admin/knowledge/vector-store-types') return { body: { items: [{ type: 'qdrant', display_name: 'Qdrant', status: 'available', stage: null, verified: false, connection_fields: [], index_fields: [] }] } }
    if (path === '/api/v1/tenants/a/admin/knowledge/vector-stores') return { body: { items: vectors } }
    if (path === '/api/v1/tenants/a/admin/knowledge/vector-stores/v1' && request.method() === 'PUT') {
      const value = request.postDataJSON() as Record<string, unknown>; writes.push(value); return { body: { ...vectors[0], ...value } }
    }
  })
  await page.goto('storage')
  await expect(page.locator('.backend-card--add')).toBeVisible()
  await expect(page.locator('.setting-drawer:visible')).toHaveCount(0)
  await page.locator('.backend-card--add').click()
  const drawer = page.locator('.setting-drawer')
  await drawer.locator('input').nth(0).fill('Local documents')
  await drawer.locator('input').nth(1).fill('/srv/documents')
  await expectResponsive(page)
  await drawer.locator('.setting-drawer__footer-right button').last().click()
  await expect(page.locator('.backend-card__title')).toHaveText('Local documents')
  await expect(page.locator('.backend-grid')).not.toContainText('/srv/documents')
  await expectResponsive(page)
  await page.goto('vector-stores')
  const card = page.locator('.store-card--clickable')
  await expect(card).toContainText('Qdrant')
  await card.focus(); await page.keyboard.press('Enter')
  await expect(drawer).toBeVisible()
  await drawer.locator('input').first().fill('Renamed Qdrant')
  await drawer.locator('.setting-drawer__footer-right button').last().click()
  await expect(page.locator('.store-card__title')).toHaveText('Renamed Qdrant')
  expect(writes).toEqual([{ name: 'Renamed Qdrant', connection_config: {}, index_config: {} }])
  await expectResponsive(page)
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await expectResponsive(page)
})


test('系统设置保存编辑展示偏好，抽屉与替换路由保持同一表单，返回关闭编辑', async ({ page, api }, testInfo) => {
  await api.signIn()
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['models:manage'] } }
    if (path === '/api/v1/tenants/a/admin/model-settings') return { body: { providers: [], defaults: {}, can_manage_tenant: true } }
  })
  await page.goto('settings')
  const navigation = page.locator('#enterprise-navigation')
  const selectMode = async (label: string) => {
    await page.locator('.setting-row').filter({ hasText: '二级编辑界面' }).locator('.t-select').click()
    await page.locator('.t-select-option:visible').filter({ hasText: label }).click()
  }
  await selectMode('抽屉')
  await navigation.getByRole('link', { name: '模型', exact: true }).click()
  await page.locator('.model-header-actions').getByRole('button', { name: '添加模型', exact: true }).click()
  await expect(page.locator('.t-drawer--open')).toBeVisible()
  await page.locator('.t-drawer--open .t-drawer__close-btn').click()
  await navigation.getByRole('link', { name: '系统设置', exact: true }).click()
  await selectMode('替换路由')
  await navigation.getByRole('link', { name: '模型', exact: true }).click()
  await page.locator('.model-header-actions').getByRole('button', { name: '添加模型', exact: true }).click()
  await expect(page).toHaveURL(/models\?editor=edit-[^&]+$/)
  await expect(page.locator('.editor-dialog-route:visible')).toBeVisible()
  await expect.poll(async () => await page.locator('.editor-dialog-route:visible .t-dialog').evaluate(element => { const rect = element.getBoundingClientRect(); return Math.abs(rect.top) <= 1 && rect.bottom <= innerHeight + 1 && rect.height >= innerHeight - 2 })).toBe(true)
  await expect(page.locator('.editor-dialog-route:visible .setting-drawer__footer')).toBeInViewport()
  await page.screenshot({ path: testInfo.outputPath('route-editor.png') })
  await page.goBack()
  await expect(page).toHaveURL(/models$/)
  await expect(page.locator('.editor-dialog-route:visible')).toHaveCount(0)
  await expectResponsive(page)
})


test('知识库、智能体与技能使用参考资源卡片，MCP注册独立于发布', async ({ page, api }, testInfo) => {
  await api.signIn()
  const knowledge = { id: 'kb1', tenant_id: 'a', ownership: 'enterprise', shared: false, name: 'Knowledge reference', description: 'Knowledge content', type: 'document', visibility: 'tenant', knowledge_count: 3, can_manage: true }
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['enterprise_kbs:manage', 'enterprise_agents:manage', 'tools:manage'] } }
    if (path === '/api/v1/tenants/a/admin/knowledge/bases') return { body: { items: [knowledge, { ...knowledge, id: 'kb2', name: 'Archive reference', description: '', type: 'faq', knowledge_count: 0 }] } }
    if (path === '/api/v1/tenants/a/admin/knowledge/bases/kb1/folders') return { body: { folders: [], root_document_count: 0, total_document_count: 0 } }
    if (path === '/api/v1/tenants/a/admin/knowledge/bases/kb1/documents') return { body: { items: [], total: 0 } }
    if (path === '/api/v1/tenants/a/admin/knowledge/bases/kb2/faq/entries') return { body: { items: [], total: 0 } }
    if (path === '/api/v1/tenants/a/admin/agents') return { body: [{ id: 'agent1', tenant_id: 'a', ownership: 'enterprise', can_maintain: true, name: 'Agent reference', description: 'Agent content', status: 'draft', runtime_type: 'native', instructions: '', published_version_id: null, model_profile_version_id: null, version_counter: 0, budgets: {}, resource_bindings: [], created_at: '2026-11-18', updated_at: '2026-11-18' }] }
    if (path === '/api/v1/tenants/a/admin/agent-tools') return { body: { tools: [], groups: [], default_tools: [], can_enable_tools: true } }
    if (path === '/api/v1/tenants/a/skills') return { body: [{ name: 'Skill reference', source: 'builtin', scope: 'builtin', source_tenant_id: 'a', version: 1, version_id: 'v1', tools: [], execution: 'sandbox', model_invocable: true, description: 'Skill content', disabled: false }] }
    if (path === '/api/v1/tenants/a/mcp-services') return { body: [{ id: 'm1', tenant_id: 'a', name: 'MCP reference', description: 'MCP content', transport: 'streamable_http', config: { url: 'https://mcp.example.test' }, enabled: true, config_epoch: 'e1', created_by: 'u', created_at: '2026-11-18', updated_at: '2026-11-18' }] }
  })
  await page.goto('knowledge')
  const navigation = page.locator('#enterprise-navigation')
  const cards = page.locator('.resource-directory-card')
  await expect(cards.locator('.card-title')).toHaveText(['Knowledge reference', 'Archive reference'])
  await expect(page.locator('.resource-grid')).toHaveCSS('gap', '10px')
  await page.screenshot({ path: testInfo.outputPath('knowledge-reference-directory.png') })
  await page.getByRole('button', { name: /^排序/ }).click()
  await page.getByText('A–Z', { exact: true }).click()
  await expect(cards.locator('.card-title')).toHaveText(['Archive reference', 'Knowledge reference'])
  const search = page.getByRole('textbox', { name: '搜索知识库名称或描述' })
  await search.fill('does not exist')
  await expect(cards).toHaveCount(0)
  await page.getByRole('button', { name: '清空', exact: true }).click()
  const documentCard = cards.filter({ hasText: 'Knowledge reference' })
  await documentCard.hover()
  await documentCard.locator('.card-more-button').click()
  await expect(page.getByText('编辑设置', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/enterprise\/knowledge$/)
  await page.locator('.header h2').click()
  await documentCard.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/knowledge\/kb1\/content$/)
  const breadcrumb = page.locator('.document-breadcrumb')
  await breadcrumb.getByRole('button', { name: 'Knowledge reference' }).click()
  await page.getByText('Archive reference', { exact: true }).click()
  await expect(page).toHaveURL(/\/knowledge\/kb2\/content$/)
  await expect(breadcrumb).toContainText('Archive reference')
  await expectResponsive(page)
  await page.setViewportSize({ width: 1280, height: 900 })
  if (await page.getByRole('button', { name: '展开侧边栏' }).isVisible()) {
    await page.getByRole('button', { name: '展开侧边栏' }).click()
  }
  await breadcrumb.getByRole('link', { name: '知识库管理' }).click()
  await navigation.getByRole('link', { name: '智能体', exact: true }).click()
  await expect(page).toHaveURL(/\/enterprise\/agents$/)
  const agentCard = cards.filter({ hasText: 'Agent reference' })
  await expect(agentCard).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('agent-reference-directory.png') })
  await agentCard.hover()
  await agentCard.locator('.card-more-button').click()
  await expect(page.getByText('编辑并发布', { exact: true })).toBeVisible()
  const archive = page.getByText('归档', { exact: true })
  await expect(archive).toBeVisible()
  await page.locator('.header h2').click()
  await navigation.getByRole('link', { name: '工具', exact: true }).click()
  await page.locator('.toolbox-tabs').getByRole('link', { name: '技能管理' }).click()
  await expect(page.locator('.skill-card')).toContainText('Skill reference')
  await page.locator('.toolbox-tabs').getByRole('link', { name: 'MCP服务注册' }).click()
  await expect(page.locator('.service-card')).toContainText('MCP reference')
  await expect(navigation.getByRole('link', { name: 'MCP服务', exact: true })).toHaveAttribute('href', /mcp-endpoints$/)
  await page.screenshot({ path: testInfo.outputPath('mcp-reference-cards.png') })
  await expectResponsive(page)
})

test('企业组织维护节点，用户管理按组织筛选并在抽屉编辑', async ({ page, api }) => {
  await api.signIn()
  const base = '/api/v1/tenants/a/admin'
  const root = { id: 'root', parent_id: null, name: 'Acme', status: 'active', source: 'manual', sync_managed: false, member_count: 0 }
  const department = { ...root, id: 'research', parent_id: 'root', name: 'Research', member_count: 1 }
  const nodes = [root, department]
  const members = ['Alice', 'Bob'].map(name => ({ tenant_id: 'a', user_id: name, role: 'contributor', status: 'active', joined_at: '2026-11-18', display_name: name }))
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === base + '/org-units/tree') return { body: nodes }
    if (path === base + '/org-units' && request.method() === 'POST') {
      const row = { ...department, ...request.postDataJSON(), member_count: 0, id: 'created' }
      nodes.push(row)
      return { body: { ...row, tenant_id: 'a', root_id: 'root' } }
    }
    if (path === base + '/org-units/created' && request.method() === 'PATCH') {
      const row = nodes.find(value => value.id === 'created')!
      Object.assign(row, request.postDataJSON())
      return { body: { ...row, tenant_id: 'a', root_id: 'root' } }
    }
    if (path === base + '/members') return { body: members }
    if (path === base + '/invitations') return { body: [] }
    if (path === base + '/org-units/research/members') return { body: [{ user_id: 'Alice', display_name: 'Alice', source: 'manual', is_primary: true }] }
  })
  await page.goto('organization')
  await expect(page.getByRole('heading', { name: '企业组织', exact: true })).toBeVisible()
  const organizationRows = page.locator('.organization-content tbody')
  await expect(organizationRows).toContainText('Research')
  await page.getByRole('button', { name: '新增组织' }).click()
  const dialog = page.locator('.t-dialog:visible')
  await dialog.locator('input').first().fill('Finance')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  const finance = organizationRows.locator('tr').filter({ hasText: 'Finance' })
  await expect(finance).toBeVisible()
  await finance.getByRole('button', { name: '编辑', exact: true }).click()
  await dialog.locator('input').first().fill('Finance operations')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(organizationRows).toContainText('Finance operations')
  expect(api.requests.some(path => path.endsWith('/members'))).toBe(false)
  await page.goto('settings')
  await page.locator('.setting-row').filter({ hasText: '二级编辑界面' }).locator('.t-select').click()
  await page.locator('.t-select-option:visible').filter({ hasText: '抽屉' }).click()
  await page.goto('members')
  const userRows = page.locator('.user-management-content tbody')
  await expect(userRows).toContainText('Bob')
  await page.locator('.organization-tree').getByRole('button', { name: /Research/ }).click()
  await expect(userRows).toContainText('Alice')
  await expect(userRows).not.toContainText('Bob')
  await userRows.getByRole('button', { name: '编辑', exact: true }).click()
  const drawer = page.locator('.t-drawer--open')
  await expect(drawer).toContainText('编辑用户')
  await expect(drawer).toContainText('组织归属')
  await expect(drawer.locator('input[readonly]').first()).toHaveValue('Alice')
  await expectResponsive(page)
})

test('系统设置主题色即时应用，刷新后保留', async ({ page, api }) => {
  await api.signIn()
  await page.goto('settings')
  const swatches = page.getByRole('radiogroup', { name: '主题色' })
  await expect(swatches.getByRole('radio')).toHaveCount(12)
  const blue = swatches.getByRole('radio', { name: '蓝色', exact: true })
  await blue.click()
  await expect(blue).toHaveAttribute('aria-checked', 'true')
  await expect.poll(() => page.evaluate(() => document.documentElement.style.getPropertyValue('--td-brand-color'))).not.toBe('')
  await page.reload()
  await expect(blue).toHaveAttribute('aria-checked', 'true')
  await expectResponsive(page)
})

test('企业模型目录按 WeKnora 布局筛选、编辑、复制、删除和调试', async ({ page, api }) => {
  await api.signIn()
  await page.setViewportSize({ width: 1440, height: 900 })
  const root = '/api/v1/tenants/a/admin/model-settings'
  const chat = { id: 'chat', name: 'Example Chat', model_type: 'chat', version_id: 'chat-v1', version: 1, options: {} }
  const embedding = { id: 'embedding', name: 'Example Embed', model_type: 'embedding', version_id: 'embed-v1', version: 1, options: {} }
  const vision = { id: 'vision', name: 'Example Vision', model_type: 'vision', version_id: 'vision-v1', version: 1, options: {} }
  const providers = [
    { id: 'north', name: 'North API', scope: 'tenant', base_url: 'https://north.example.test', key_configured: true, key_mask: '****', models: [chat, vision] },
    { id: 'south', name: 'South API', scope: 'tenant', base_url: 'https://south.example.test', key_configured: true, key_mask: '****', models: [embedding] },
  ]
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['models:manage'] } }
    if (path === root) return { body: { providers, defaults: { tenant: { chat: 'chat-v1' } }, can_manage_tenant: true } }
    if (path === root + '/providers/north/models/chat/debug') {
      expect(request.postDataJSON()).toMatchObject({ text: 'Reply OK', max_output_tokens: 512 })
      return { body: { ok: true, result: { type: 'chat', text: 'Debug response' } } }
    }
    if (path === root + '/providers/north/models/vision/debug-media') {
      expect(request.headers()['content-type']).toContain('multipart/form-data')
      return { body: { ok: true, result: { type: 'vision', text: 'Image description' } } }
    }
    if (path === root + '/providers/north/models/chat/copy') {
      const { suffix } = request.postDataJSON()
      const row = { ...chat, id: 'copied-chat', version_id: 'copied-chat-v1', display_name: `Example Chat ${suffix}` }
      providers[0].models.push(row)
      return { body: { id: row.id, version_id: row.version_id } }
    }
    if (path === root + '/providers/north/models/chat/configuration' && request.method() === 'DELETE') {
      return { status: 409, body: { error: { code: 'model_in_use', details: { agents: 1, knowledge_bases: 0, memory: 0 } } } }
    }
    if (path === root + '/providers/south/models/embedding/configuration' && request.method() === 'DELETE') {
      providers[1].models = []
      return { body: { status: 'disabled' } }
    }
  })
  await page.goto('models')
  const cards = page.locator('.model-grid article')
  const typeTabs = page.locator('.model-type-tabs')
  await expect(page.getByRole('heading', { name: '模型配置' })).toBeVisible()
  await expect(cards).toHaveCount(3)
  await expect(typeTabs.locator('.model-tab-count')).toHaveText(['3', '1', '1', '0', '1', '0'])
  await expect(page.locator('.model-grid > :last-child')).toHaveText('添加模型')
  await expect(page.getByRole('button', { name: '服务商', exact: true })).toHaveCount(0)

  const search = page.locator('.model-search input')
  expect((await search.boundingBox())!.x).toBeGreaterThan((await typeTabs.boundingBox())!.x)
  expect((await cards.nth(0).boundingBox())!.y).toBe((await cards.nth(1).boundingBox())!.y)
  await search.fill('  north api  ')
  await expect(cards).toHaveCount(2)
  await expect(cards.first()).toContainText('Example Chat')
  await search.fill('没有这个模型')
  await expect(page.getByText('无结果', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '清空', exact: true }).click()

  const chatCard = cards.filter({ has: page.getByRole('button', { name: 'Example Chat', exact: true }) })
  const drawer = page.locator('.setting-drawer:visible')
  await chatCard.getByRole('button', { name: 'Example Chat' }).press('Enter')
  await expect(drawer).toContainText('编辑模型')
  await expect(drawer).toContainText('模型来源')
  await expect(drawer.getByLabel('Base URL')).toHaveValue('https://north.example.test')
  await expect(drawer.getByLabel('API Key')).toHaveValue('')
  await expect(drawer.getByText('接口协议', { exact: true })).toHaveCount(0)
  await drawer.getByRole('button', { name: '高级选项' }).click()
  await expect(drawer.getByText('接口协议', { exact: true })).toBeVisible()
  await drawer.getByRole('button', { name: '取消', exact: true }).click()

  await page.getByRole('button', { name: '模型测试', exact: true }).click()
  await drawer.locator('.t-select').first().click()
  await page.locator('.t-select-option:visible').getByText('Example Chat', { exact: true }).click()
  await drawer.getByLabel('输入内容').fill('Reply OK')
  await drawer.getByRole('button', { name: '运行测试' }).click()
  await expect(drawer.getByText('Debug response', { exact: true })).toBeVisible()
  await drawer.getByRole('button', { name: '视觉', exact: true }).click()
  await drawer.locator('.t-select').first().click()
  await page.locator('.t-select-option:visible').getByText('Example Vision', { exact: true }).click()
  await drawer.getByLabel('图片文件').setInputFiles({ name: 'sample.png', mimeType: 'image/png', buffer: Buffer.from('sample') })
  await drawer.getByRole('button', { name: '运行测试' }).click()
  await expect(drawer.getByText('Image description', { exact: true })).toBeVisible()
  await drawer.getByRole('button', { name: '关闭', exact: true }).click()

  const confirmDelete = async (card: typeof chatCard) => {
    await card.getByRole('button', { name: '删除', exact: true }).click()
    await page.locator('.t-popconfirm:visible').getByRole('button', { name: '删除', exact: true }).click()
  }
  await confirmDelete(chatCard)
  const conflict = page.locator('.t-dialog:visible')
  await expect(conflict).toContainText('模型无法删除')
  await expect(conflict).toContainText('智能体（1）')
  await page.keyboard.press('Escape')

  await typeTabs.getByText('Embedding', { exact: true }).click()
  await expect(cards).toHaveCount(1)
  await confirmDelete(cards.first())
  await expect(cards).toHaveCount(0)
  await typeTabs.getByText('全部', { exact: true }).click()
  await expectResponsive(page)
  expect((await search.boundingBox())!.y).toBeGreaterThan((await typeTabs.boundingBox())!.y)

  const menu = chatCard.getByRole('button', { name: '展开' })
  await menu.press('Enter')
  const edit = page.getByRole('button', { name: '编辑', exact: true })
  const copy = page.getByRole('button', { name: '复制', exact: true })
  await expect(copy).toBeInViewport({ ratio: 1 })
  const lineCounts = await page.locator('.model-actions-panel:visible').getByRole('button').evaluateAll(buttons =>
    buttons.map(button => {
      const range = document.createRange()
      range.selectNodeContents(button.querySelector('.t-button__text') ?? button)
      return new Set(Array.from(range.getClientRects(), rect => rect.y)).size
    }),
  )
  expect(lineCounts).toEqual([1, 1])
  await page.keyboard.press('Tab')
  await expect(edit).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(menu).toBeFocused()
  await menu.click()
  await copy.click()
  const copied = cards.getByRole('button', { name: 'Example Chat 副本' })
  await expect(copied).toBeVisible()
  await copied.click()
  await expect(drawer.getByLabel('模型名称', { exact: true })).toHaveValue('Example Chat')
  await expect(drawer.getByLabel('显示名称（可选）')).toHaveValue('Example Chat 副本')
  await drawer.getByRole('button', { name: '取消', exact: true }).click()

  await page.goto('models/defaults')
  await expect(page.locator('.defaults-panel .t-select input').first()).toHaveValue('North API · Example Chat')
})

test('企业模型用同一抽屉新增与修改接入，测试当前草稿并可重试保存', async ({ page, api }) => {
  await api.signIn()
  const root = '/api/v1/tenants/a/admin/model-settings'
  const writes: unknown[] = [], draftTests: unknown[] = []
  let provider: { id: string; name: string; base_url: string; scope: string; key_configured: boolean; key_mask: string; models: unknown[] } | undefined
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['models:manage'] } }
    if (path === root) return { body: { providers: provider ? [provider] : [], defaults: {}, can_manage_tenant: true } }
    if (path === root + '/test') {
      draftTests.push(request.postDataJSON())
      return { body: { ok: true, message: 'Draft connection verified' } }
    }
    if (path === root + '/models' && request.method() === 'POST') {
      const input = request.postDataJSON()
      writes.push(input)
      if (writes.length === 1) return { status: 422, body: { error: 'Model rejected' } }
      const { provider: connection, ...model } = input
      const row = { ...model, id: 'model', version_id: 'model-v1', version: 1 }
      provider = { id: 'new', name: connection.name, base_url: connection.base_url, scope: 'tenant', key_configured: true, key_mask: '****', models: [row] }
      return { body: { id: row.id, version_id: row.version_id } }
    }
    if (path === root + '/providers/new/models/model/configuration' && request.method() === 'PUT' && provider) {
      const input = request.postDataJSON()
      writes.push(input)
      const { provider: connection, ...model } = input
      provider = { ...provider, base_url: connection.base_url, models: [{ ...model, id: 'model', version_id: 'model-v2', version: 2 }] }
      return { body: { id: 'model', version_id: 'model-v2' } }
    }
  })

  await page.setViewportSize({ width: 375, height: 900 })
  await page.goto('models')
  await page.locator('.model-card--add').click()
  const editor = page.locator('.setting-drawer:visible')
  const save = editor.getByRole('button', { name: '保存并关闭', exact: true })
  const service = editor.locator('.t-select').first()
  const address = editor.getByLabel('Base URL')
  const key = editor.getByLabel('API Key')
  await expect(save).toBeInViewport()
  await save.click()
  await expect(editor.getByRole('alert')).toBeVisible()

  const choose = async (label: string) => {
    await service.click()
    await page.locator('.t-select-option:visible').getByText(label, { exact: true }).click()
  }
  await choose('OpenAI')
  await expect(address).toHaveValue('https://api.openai.com/v1')
  await key.fill('example-key-for-openai')
  await choose('DeepSeek')
  await expect(address).toHaveValue('https://api.deepseek.com')
  await expect(key).toHaveValue('')
  await editor.locator('.t-select').nth(1).click()
  await page.locator('.t-select-option:visible').getByText('deepseek-flash', { exact: true }).click()
  await address.fill('https://gateway.example.test/v1')
  await key.fill('example-gateway-key')
  await editor.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(editor.getByRole('status')).toHaveText('Draft connection verified')
  expect(draftTests).toEqual([{
    scope: 'tenant', base_url: 'https://gateway.example.test/v1', api_key: 'example-gateway-key',
    model_name: 'deepseek-flash', model_type: 'chat', options: { protocol: 'openai_chat_completions', reasoning_effort: '' },
  }])
  await save.click()
  await expect(editor.getByRole('alert')).toContainText('模型配置保存失败')
  await expect(key).toHaveValue('example-gateway-key')
  await save.click()
  await expect(editor).toHaveCount(0)
  const card = page.locator('.model-grid article').getByRole('button', { name: 'deepseek-flash' })
  await card.click()
  await expect(editor).toContainText('编辑模型')
  await expect(address).toHaveValue('https://gateway.example.test/v1')
  await expect(key).toHaveValue('')
  await address.fill('https://another.example.test/v1')
  await save.click()
  await expect(editor.getByRole('alert')).toContainText('修改 API 地址需要重新填写 API Key。')
  expect(writes).toHaveLength(2)
  await key.fill('example-new-key')
  await save.click()
  await expect(editor).toHaveCount(0)
  expect(writes[2]).toMatchObject({
    name: 'deepseek-flash', model_type: 'chat',
    provider: { name: 'DeepSeek', base_url: 'https://another.example.test/v1', api_key: 'example-new-key', scope: 'tenant' },
  })
})

test('IM 集成从发布集成进入并绑定已登记的企业微信应用', async ({ page, api }) => {
  await api.signIn()
  const root = '/api/v1/tenants/a'
  const row = { id: 'channel', name: '企业客服', agent_id: 'agent', kind: 'wecom_app', status: 'active', owner_user_id: 'u', bound: true, review_note: null }
  const writes: unknown[] = []
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === root + '/me/permissions') return { body: { apis: ['org:manage', 'enterprise_agents:manage'] } }
    if (path === root + '/admin/agents') return { body: [
      { id: 'agent', tenant_id: 'a', name: '客服智能体', ownership: 'enterprise', can_maintain: true, status: 'published' },
      { id: 'personal', tenant_id: 'a', name: '个人智能体', ownership: 'personal', can_maintain: false, status: 'published' },
    ] }
    if (path === root + '/admin/channels') return { body: { items: writes.length ? [row] : [] } }
    if (path === root + '/admin/wecom') return { body: { apps: [{ id: 'app', name: '微信应用', purpose: 'agent', nexus_agent_id: 'agent', status: 'active' }] } }
    if (path === root + '/agents/agent/channels' && request.method() === 'POST') {
      writes.push(request.postDataJSON())
      return { body: row }
    }
  })
  await page.goto('settings')
  await page.locator('#enterprise-navigation').getByRole('link', { name: 'IM 集成' }).click()
  await expect(page.getByRole('heading', { name: 'IM 集成' })).toBeVisible()
  await page.locator('.channel-card--add').click()
  const drawer = page.locator('.setting-drawer:visible')
  const select = drawer.locator('.t-select')
  await select.first().click()
  await expect(page.locator('.t-select-option:visible').filter({ hasText: '个人智能体' })).toHaveCount(0)
  await page.locator('.t-select-option:visible').filter({ hasText: '客服智能体' }).click()
  await drawer.getByRole('textbox', { name: '渠道名称' }).fill('企业客服')
  await expect(drawer.locator('.im-step')).toHaveText(['1基本信息', '2连接设置', '3文件存储', '4平台凭证'])
  const next = drawer.getByRole('button', { name: '下一步', exact: true })
  await next.click()
  await expect(drawer.getByText('Webhook', { exact: true })).toBeVisible()
  await next.click()
  await expect(drawer.getByText('渠道使用所选智能体的知识库配置。')).toBeVisible()
  await next.click()
  await select.last().click()
  await page.locator('.t-select-option:visible').filter({ hasText: '微信应用' }).click()
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.channel-card__title').filter({ hasText: '企业客服' })).toBeVisible()
  expect(writes).toEqual([{ kind: 'wecom_app', name: '企业客服', wecom_app_id: 'app' }])
  await expectResponsive(page)
})

test('MCP 发布从新增卡片保存端点并展示一次性配置', async ({ page, api }) => {
  await api.signIn()
  const root = '/api/v1/tenants/a/admin'
  const writes: unknown[] = []
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['tools:manage'] } }
    if (path === root + '/knowledge/bases') return { body: { items: [] } }
    if (path === root + '/mcp-endpoints') {
      if (request.method() === 'GET') return { body: [] }
      const input = request.postDataJSON()
      writes.push(input)
      return { body: { ...input, id: 'endpoint', tenant_id: 'a', enabled: true, created_by: 'u', token: 'one-time-mock-token' } }
    }
  })
  await page.goto('mcp-endpoints')
  await expect(page.locator('.channels-count')).toHaveText('0')
  await page.locator('.channel-card--add').click()
  const editor = page.locator('.setting-drawer:visible')
  await editor.locator('input').first().fill('new-endpoint')
  await editor.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.token-snippet')).toContainText('one-time-mock-token')
  await expect(page.locator('.channel-card__title').filter({ hasText: 'new-endpoint' })).toBeVisible()
  expect(writes).toEqual([{ name: 'new-endpoint', description: '', tool_allowlist: [], kb_ids: [] }])
})

test('IM 微信渠道按企业策略接入并生成绑定二维码', async ({ page, api }) => {
  await api.signIn()
  const root = '/api/v1/tenants/a'
  const row = { id: 'wechat', name: '微信', agent_id: 'personal', kind: 'wechat', status: 'binding', owner_user_id: 'u', bound: false, review_note: null }
  const writes: unknown[] = []
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === root + '/me/permissions') return { body: { apis: ['enterprise_agents:manage'] } }
    if (path === root + '/admin/agents') return { body: [
      { id: 'personal', tenant_id: 'a', name: '个人智能体', ownership: 'personal', can_maintain: true, status: 'published' },
    ] }
    if (path === root + '/admin/channels') return { body: { items: writes.length ? [row] : [] } }
    if (path === root + '/admin/policy') return { body: { personal_external_channels: true } }
    if (path === root + '/agents/personal/channels' && request.method() === 'POST') {
      writes.push(request.postDataJSON())
      return { body: row }
    }
    if (path === root + '/channels/wechat/wechat/qr') return { body: { qrcode_url: 'https://example.test/mock-binding' } }
    if (path === root + '/channels/wechat/wechat/status') return { body: { status: 'wait' } }
  })
  await page.goto('channels')
  await page.locator('.channel-card--add').click()
  const drawer = page.locator('.setting-drawer:visible')
  await drawer.locator('.t-select').first().click()
  await page.locator('.t-select-option:visible').filter({ hasText: '个人智能体' }).click()
  await expect(drawer.locator('.t-select').last().locator('input')).toHaveValue('微信')
  const next = drawer.getByRole('button', { name: '下一步', exact: true })
  for (let step = 0; step < 3; step++) await next.click()
  await drawer.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.t-qrcode')).toBeVisible()
  expect(writes).toEqual([{ kind: 'wechat', name: '微信' }])
})

test('沙箱引擎读取部署档位并按引擎和名称筛选', async ({ page, api }) => {
  await api.signIn()
  api.handle(request => {
    if (new URL(request.url()).pathname !== '/api/v1/tenants/a/agent-tools') return
    return { body: { tools: [], groups: [], default_tools: [], can_enable_tools: true, sandbox_profiles: [
      { name: 'isolated', type: 'docker', default: true, available: true, reason: '' },
      { name: 'pending', type: 'bwrap', default: false, available: false, reason: 'sandbox_not_accepted' },
    ] } }
  })
  await page.goto('settings')
  await page.locator('#enterprise-navigation').getByRole('link', { name: '沙箱引擎' }).click()
  await expect(page.locator('.sandbox-card')).toHaveCount(2)
  await expect(page.locator('.sandbox-card').filter({ hasText: 'pending' })).toContainText('尚未通过隔离验收')
  await page.locator('.sandbox-type-tabs').getByText('Docker 1', { exact: true }).click()
  await expect(page.locator('.sandbox-card')).toContainText('isolated')
  await page.getByRole('textbox', { name: '搜索' }).fill('not-matching')
  await expect(page.locator('.sandbox-card')).toHaveCount(0)
  await expectResponsive(page)
})

test('企业知识库确认上传、切换目标目录并保留本地文件夹层级', async ({ page, api }, testInfo) => {
  page.setDefaultTimeout(15000)
  await api.signIn()
  const root = '/api/v1/tenants/a/admin/knowledge/bases', kb = root + '/kb'
  const base = { id: 'kb', tenant_id: 'a', ownership: 'enterprise', shared: false, name: '目录测试',
    description: '', type: 'document', visibility: 'tenant', knowledge_count: 0, can_manage: true }
  const documents: Array<{ filename: string; folder_path: string } & Record<string, unknown>> = []
  let created = ''
  const node = (path: string, children: unknown[] = []) => ({
    path, name: path.split('/').at(-1), document_count: documents.filter(doc => doc.folder_path === path).length,
    total_count: documents.filter(doc => doc.folder_path === path || doc.folder_path.startsWith(path + '/')).length, children,
  })
  api.handle(request => {
    const url = new URL(request.url())
    if (url.pathname === root) return { body: { items: [base] } }
    if (url.pathname === kb + '/folders') {
      if (request.method() === 'POST') {
        created = request.postDataJSON().path
        return { status: 201, body: { path: created } }
      }
      const nested = created + '/local/nested'
      return { body: { root_document_count: 0, total_document_count: documents.length,
        folders: created ? [node(created, documents.some(doc => doc.folder_path === nested)
          ? [node(created + '/local', [node(nested)])] : [])] : [] } }
    }
    if (url.pathname === kb + '/documents') {
      if (request.method() === 'POST') {
        const parts = request.postData()?.match(/name="filename"\r\n\r\n([^\r]+)\r\n/)
        const name = parts?.[1] ?? ''
        expect(['目标/plain.txt', '目标/local/nested/nested.txt']).toContain(name)
        const cut = name.lastIndexOf('/')
        const document = { id: String(documents.length + 1), kb_id: 'kb', filename: name.slice(cut + 1),
          file_type: 'txt', status: 'active', parse_status: 'pending', folder_path: name.slice(0, cut),
          summary: null, tag_ids: [], current_version: null, latest_version: null, created_at: '', updated_at: '' }
        documents.push(document)
        return { status: 201, body: { document, deduplicated: false } }
      }
      const items = documents.filter(doc => doc.folder_path === url.searchParams.get('folder_path'))
      return { body: { items, total: items.length } }
    }
  })
  await page.goto('knowledge/kb/content')
  const tree = page.locator('.kb-folder-tree')
  await tree.getByRole('button', { name: '新建子目录' }).click()
  const dialog = page.locator('.t-dialog:visible')
  await dialog.getByRole('textbox').fill('目标')
  await dialog.getByRole('button', { name: '创建', exact: true }).click()
  await expect(tree.locator('.kb-folder-row.active')).toContainText('目标')

  const fileInput = page.locator('.content-actions input[type="file"]:not([webkitdirectory])')
  const upload = page.getByRole('dialog', { name: '上传文档确认' })
  const plain = {
    name: 'plain.txt', mimeType: 'text/plain', buffer: Buffer.from('plain'),
  }
  await fileInput.setInputFiles(plain)
  await expect(upload.getByText('plain.txt', { exact: true })).toBeVisible()
  await expect(upload.getByText('使用知识库默认配置')).toBeVisible()
  await expect(upload.getByRole('button', { name: '更改上传位置' })).toContainText('目标')
  await expect(upload.getByRole('button', { name: '关闭', exact: true })).toBeFocused()
  await page.setViewportSize({ width: 375, height: 740 })
  await expect(upload.getByRole('button', { name: '确认上传并解析' })).toBeInViewport()
  await page.keyboard.press('Escape')
  await expect(upload).toHaveCount(0)
  expect(documents).toHaveLength(0)
  await page.setViewportSize({ width: 1440, height: 900 })

  await tree.locator('.kb-folder-row').first().click()
  await fileInput.setInputFiles(plain)
  await upload.getByRole('button', { name: '更改上传位置' }).click()
  await page.locator('.upload-destination-popup:visible').getByRole('button', { name: '目标', exact: true }).press('Enter')
  await expect(upload.getByRole('button', { name: '更改上传位置' })).toContainText('目标')
  await upload.getByRole('button', { name: '继续添加' }).click()
  await expect(page.getByText('上传文件夹', { exact: true })).toBeVisible()
  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByText('上传文档', { exact: true }).click(),
  ])
  await chooser.setFiles({
    name: 'discard.txt', mimeType: 'text/plain', buffer: Buffer.from('discard'),
  })
  await upload.getByRole('listitem').filter({ hasText: 'discard.txt' }).getByRole('button', { name: '移除' }).click()
  await upload.getByRole('button', { name: '确认上传并解析' }).click()
  await expect.poll(() => documents.length).toBe(1)
  await tree.locator('.kb-folder-row').filter({ hasText: '目标' }).click()
  await expect(page.getByText('plain.txt', { exact: true })).toBeVisible()
  const local = testInfo.outputPath('local')
  mkdirSync(join(local, 'nested'), { recursive: true })
  writeFileSync(join(local, 'nested', 'nested.txt'), 'nested')
  await page.locator('.content-actions input[webkitdirectory]').setInputFiles(local)
  await expect(upload).toContainText('local/nested')
  await upload.getByRole('button', { name: '确认上传并解析' }).click()
  await expect.poll(() => documents.length).toBe(2)
  await expect(tree.locator('.kb-folder-row').filter({ hasText: 'local' })).toBeVisible()
  await tree.locator('.kb-folder-row').filter({ hasText: 'local' }).getByRole('button', { name: '展开该文件夹' }).click()
  await tree.locator('.kb-folder-row').filter({ hasText: 'nested' }).click()
  await expect(page.getByText('nested.txt', { exact: true })).toBeVisible()
  await expectResponsive(page)
})
