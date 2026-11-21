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
  await expect(page.locator('#enterprise-navigation button')).toHaveText(['企业', '知识库', '发布集成', '数据和扩展', '权限', '系统'])
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

test('一级菜单默认收起并互斥展开，图标侧栏可用键盘访问', async ({ page, api }, testInfo) => {
  await api.signIn()
  api.handle(request => new URL(request.url()).pathname === '/api/v1/tenants/a/me/permissions'
    ? { body: { apis: ['org:manage', 'members:manage', 'roles:manage', 'models:manage', 'tools:manage', 'enterprise_kbs:manage', 'enterprise_agents:manage', 'audit:read', 'policy:manage'] } } : undefined)
  await page.goto('')
  const navigation = page.locator('#enterprise-navigation')
  await expect(navigation.getByRole('button')).toHaveText(['企业', '智能体', '知识库', '模型', '发布集成', '数据和扩展', '工具箱', '权限', '系统'])
  await expect(navigation.locator('a')).toHaveCount(20)
  await expect(navigation.getByRole('link')).toHaveCount(0)
  const system = navigation.getByRole('button', { name: '系统', exact: true })
  const enterprise = navigation.getByRole('button', { name: '企业', exact: true })
  const integrations = navigation.getByRole('button', { name: '发布集成', exact: true })
  await expect(system).toHaveClass(/\bactive\b/)
  await page.screenshot({ path: testInfo.outputPath('grouped-navigation.png') })
  await enterprise.focus()
  await page.keyboard.press('Enter')
  await expect(enterprise).toHaveAttribute('aria-expanded', 'true')
  await expect(navigation.getByRole('link')).toHaveText(['企业空间', '企业策略', '企业组织'])
  await integrations.click()
  await expect(enterprise).toHaveAttribute('aria-expanded', 'false')
  await expect(navigation.getByRole('link')).toHaveText(['企业微信', 'MCP服务发布'])
  await integrations.click()
  await expect(navigation.getByRole('link')).toHaveCount(0)
  await expect(page).toHaveURL(/\/enterprise\/settings$/)
  await page.getByRole('button', { name: '收起侧边栏' }).click()
  const data = navigation.getByRole('button', { name: '数据和扩展', exact: true })
  await expect(data).toHaveAttribute('title', '数据和扩展')
  await data.focus()
  await page.keyboard.press('Space')
  await expect(data).toHaveAttribute('aria-expanded', 'true')
  const parser = navigation.getByRole('link', { name: '解析引擎' })
  await expect(parser).toHaveAttribute('title', '解析引擎')
  await expectResponsive(page)
  await expect(parser).toBeVisible()
  await page.reload()
  await expect(data).toHaveAttribute('aria-expanded', 'false')
  await expect(navigation.getByRole('link')).toHaveCount(0)
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
  const data = navigation.getByRole('button', { name: '数据和扩展', exact: true })
  await data.click()
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
  await expect(data).toHaveAttribute('aria-expanded', 'true')
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
  const modelsMenu = navigation.getByRole('button', { name: '模型', exact: true })
  const settingsMenu = navigation.getByRole('button', { name: '系统', exact: true })
  const selectMode = async (label: string) => {
    await page.locator('.setting-row').filter({ hasText: '二级编辑界面' }).locator('.t-select').click()
    await page.locator('.t-select-option:visible').filter({ hasText: label }).click()
  }
  await selectMode('抽屉')
  await modelsMenu.click()
  await navigation.getByRole('link', { name: '模型管理', exact: true }).click()
  await page.getByRole('button', { name: '添加服务商', exact: true }).click()
  await expect(page.locator('.t-drawer--open')).toBeVisible()
  await page.locator('.t-drawer--open .t-drawer__close-btn').click()
  await settingsMenu.click()
  await navigation.getByRole('link', { name: '系统设置', exact: true }).click()
  await selectMode('替换路由')
  await modelsMenu.click()
  await navigation.getByRole('link', { name: '模型管理', exact: true }).click()
  await page.getByRole('button', { name: '添加服务商', exact: true }).click()
  await expect(page).toHaveURL(/models\?editor=edit-[^&]+$/)
  await expect(page.locator('.editor-dialog-route:visible')).toBeVisible()
  await expect.poll(async () => await page.locator('.editor-dialog-route:visible .t-dialog').evaluate(element => { const rect = element.getBoundingClientRect(); return Math.abs(rect.top) <= 1 && rect.bottom <= innerHeight + 1 && rect.height >= innerHeight - 2 })).toBe(true)
  await expect(page.locator('.editor-dialog-route:visible .t-dialog__footer')).toBeInViewport()
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
    if (path === '/api/v1/tenants/a/admin/knowledge/bases/kb1/documents') return { body: { items: [], total: 0 } }
    if (path === '/api/v1/tenants/a/admin/knowledge/bases/kb2/faq/entries') return { body: { items: [], total: 0 } }
    if (path === '/api/v1/tenants/a/admin/agents') return { body: [{ id: 'agent1', tenant_id: 'a', ownership: 'enterprise', can_maintain: true, name: 'Agent reference', description: 'Agent content', status: 'draft', runtime_type: 'native', instructions: '', published_version_id: null, model_profile_version_id: null, version_counter: 0, budgets: {}, resource_bindings: [], created_at: '2026-11-18', updated_at: '2026-11-18' }] }
    if (path === '/api/v1/tenants/a/skills') return { body: [{ name: 'Skill reference', source: 'builtin', scope: 'builtin', source_tenant_id: 'a', version: 1, version_id: 'v1', tools: [], execution: 'sandbox', model_invocable: true, description: 'Skill content', disabled: false }] }
    if (path === '/api/v1/tenants/a/mcp-services') return { body: [{ id: 'm1', tenant_id: 'a', name: 'MCP reference', description: 'MCP content', transport: 'streamable_http', config: { url: 'https://mcp.example.test' }, enabled: true, config_epoch: 'e1', created_by: 'u', created_at: '2026-11-18', updated_at: '2026-11-18' }] }
  })
  await page.goto('knowledge')
  const navigation = page.locator('#enterprise-navigation')
  const cards = page.locator('.resource-directory-card')
  await expect(cards.locator('.card-title')).toHaveText(['Knowledge reference', 'Archive reference'])
  await expect(page.locator('.resource-grid')).toHaveCSS('gap', '10px')
  await page.screenshot({ path: testInfo.outputPath('knowledge-reference-directory.png') })
  await page.getByRole('button', { name: '排序' }).click()
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
  await navigation.getByRole('button', { name: '智能体', exact: true }).click()
  await navigation.getByRole('link', { name: '智能体管理' }).click()
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
  await navigation.getByRole('button', { name: '工具箱', exact: true }).click()
  await navigation.getByRole('link', { name: '技能管理' }).click()
  await expect(page.locator('.skill-card')).toContainText('Skill reference')
  await navigation.getByRole('link', { name: 'MCP服务注册' }).click()
  await expect(page.locator('.service-card')).toContainText('MCP reference')
  await navigation.getByRole('button', { name: '发布集成', exact: true }).click()
  await expect(navigation.getByRole('link', { name: 'MCP服务发布' })).toHaveAttribute('href', /mcp-endpoints$/)
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

test('企业模型目录按类型和服务商筛选，并从卡片编辑与添加模型', async ({ page, api }) => {
  await api.signIn()
  await page.setViewportSize({ width: 1440, height: 900 })
  const root = '/api/v1/tenants/a/admin/model-settings'
  const chat = { id: 'chat', name: 'Example Chat', model_type: 'chat', version_id: 'chat-v1', version: 1, options: {} }
  const embedding = { id: 'embedding', name: 'Example Embed', model_type: 'embedding', version_id: 'embed-v1', version: 1, options: {} }
  const providers = [
    { id: 'north', name: 'North API', scope: 'tenant', base_url: 'https://north.example.test', key_configured: true, key_mask: '****', models: [chat] },
    { id: 'south', name: 'South API', scope: 'tenant', base_url: 'https://south.example.test', key_configured: true, key_mask: '****', models: [embedding] },
  ]
  const writes: unknown[] = []
  const draftTests: unknown[] = []
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['models:manage'] } }
    if (path === root) return { body: { providers, defaults: { tenant: { chat: 'chat-v1' } }, can_manage_tenant: true } }
    if (path === root + '/providers/north/models/chat/test') return { body: { ok: true, message: 'Connection verified' } }
    if (path === root + '/test' && request.method() === 'POST') {
      draftTests.push(request.postDataJSON())
      return { body: { ok: true, message: 'Draft connection verified' } }
    }
    if (path === root + '/providers/north/models/chat/copy' && request.method() === 'POST') {
      const { suffix } = request.postDataJSON()
      const row = { ...chat, id: 'copied-chat', version_id: 'copied-chat-v1', display_name: `Example Chat ${suffix}` }
      providers[0].models.push(row)
      return { body: { id: row.id, version_id: row.version_id } }
    }
    if (path === root + '/providers/south/models' && request.method() === 'POST') {
      const input = request.postDataJSON()
      writes.push(input)
      const row = { ...embedding, ...input, id: 'new', version_id: 'new-v1' }
      providers[1].models.push(row)
      return { body: row }
    }
    if (path === root + '/providers/south/models/embedding' && request.method() === 'DELETE') {
      providers[1].models = providers[1].models.filter(model => model.id !== 'embedding')
      return { body: { status: 'disabled' } }
    }
  })
  await page.goto('models')
  const cards = page.locator('.model-grid article')
  const typeTabs = page.locator('.model-type-tabs')
  await expect(cards).toHaveCount(2)
  await expect(typeTabs.locator('.model-tab-count')).toHaveText(['2', '1', '1', '0', '0', '0'])
  await expect(page.locator('.model-grid > :last-child')).toHaveText('添加模型')

  const search = page.locator('.model-search input')
  expect((await search.boundingBox())!.x).toBeGreaterThan((await typeTabs.boundingBox())!.x)
  expect((await cards.nth(0).boundingBox())!.y).toBe((await cards.nth(1).boundingBox())!.y)
  await search.fill('  north api  ')
  await expect(cards).toHaveCount(1)
  await expect(cards).toContainText('Example Chat')
  await search.fill('没有这个模型')
  await expect(page.getByText('无结果', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '清空', exact: true }).click()
  await expect(cards).toHaveCount(2)

  const chatCard = cards.filter({ hasText: 'Example Chat' })
  await chatCard.getByRole('button', { name: '测试连接' }).click()
  await expect(chatCard.getByRole('status')).toHaveText('Connection verified')
  await chatCard.getByRole('button', { name: 'Example Chat' }).press('Enter')
  let dialog = page.locator('.t-dialog:visible')
  await expect(dialog).toContainText('编辑模型并创建新版本')
  await expect(dialog.locator('.t-select input').first()).toHaveValue('North API')
  await dialog.getByRole('button', { name: '取消', exact: true }).click()

  const providerMenu = page.getByRole('button', { name: '服务商', exact: true })
  await providerMenu.press('Enter')
  await expect(providerMenu).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'North API · 编辑服务商' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(providerMenu).toBeFocused()
  await providerMenu.click()
  await page.getByRole('button', { name: 'South API · 编辑服务商' }).click()
  dialog = page.locator('.t-dialog:visible')
  await expect(dialog).toContainText('编辑企业模型服务商')
  await expect(dialog.locator('input[type="password"]')).toHaveValue('')
  await dialog.getByRole('button', { name: '取消', exact: true }).click()

  await typeTabs.getByText('向量化', { exact: true }).click()
  await expect(cards).toHaveCount(1)
  await page.locator('.model-card--add').click()
  dialog = page.locator('.t-dialog:visible')
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  await dialog.locator('.t-select').first().click()
  await page.locator('.t-select-option:visible').filter({ hasText: 'South API' }).click()
  await dialog.getByRole('textbox', { name: '服务商模型名称' }).fill('New Embed')
  await dialog.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(dialog.getByRole('status')).toHaveText('Draft connection verified')
  expect(draftTests).toEqual([{
    scope: 'tenant', provider_id: 'south', base_url: 'https://south.example.test', model_name: 'New Embed',
    model_type: 'embedding', options: { protocol: 'openai_chat_completions', reasoning_effort: '' },
  }])
  await dialog.getByRole('textbox', { name: '服务商模型名称' }).fill('New Embedding')
  await expect(dialog.getByRole('status')).toHaveCount(0)
  await dialog.getByRole('textbox', { name: '服务商模型名称' }).fill('New Embed')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(cards).toHaveCount(2)
  expect(writes).toEqual([{
    name: 'New Embed', model_type: 'embedding', options: { protocol: 'openai_chat_completions', reasoning_effort: '' },
  }])

  await cards.filter({ hasText: 'Example Embed' }).getByRole('button', { name: '展开' }).click()
  await page.getByText('停用', { exact: true }).click()
  await expect(page.locator('.t-dialog:visible')).toContainText('Example Embed')
  await page.locator('.t-dialog:visible .t-dialog__footer button').last().click()
  await expect(cards).toHaveCount(1)
  await expect(cards).toContainText('New Embed')
  const sections = page.locator('.model-sections')
  await sections.getByText('企业默认模型', { exact: true }).click()
  await expect(page.locator('.defaults-panel .t-select input').first()).toHaveValue('North API · Example Chat')
  await sections.getByText('模型管理', { exact: true }).click()
  await expect(cards).toHaveCount(1)
  await expectResponsive(page)
  expect((await search.boundingBox())!.y).toBeGreaterThan((await typeTabs.boundingBox())!.y)
  await expect(page.locator('.model-card--add')).toBeInViewport()

  await typeTabs.getByText('全部', { exact: true }).click()
  await chatCard.getByRole('button', { name: '展开' }).click()
  await page.getByRole('button', { name: '复制', exact: true }).click()
  const copied = cards.filter({ hasText: 'Example Chat 副本' })
  await expect(copied).toHaveCount(1)
  await copied.getByRole('button', { name: 'Example Chat 副本' }).click()
  dialog = page.locator('.t-dialog:visible')
  await expect(dialog.getByRole('textbox', { name: '服务商模型名称' })).toHaveValue('Example Chat')
  await expect(dialog.getByRole('textbox', { name: '显示名称（可选）' })).toHaveValue('Example Chat 副本')
})

test('企业服务商模板预填地址并清空密钥，编辑地址要求新密钥', async ({ page, api }) => {
  await api.signIn()
  const root = '/api/v1/tenants/a/admin/model-settings'
  let provider: { id: string; name: string; base_url: string; scope: string; key_configured: boolean; key_mask: string; models: unknown[] } | undefined
  const writes: unknown[] = []
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['models:manage'] } }
    if (path === root) return { body: { providers: provider ? [provider] : [], defaults: {}, can_manage_tenant: true } }
    if (path === root + '/providers' && request.method() === 'POST' ||
        path === root + '/providers/new' && request.method() === 'PUT') {
      const input = request.postDataJSON()
      writes.push(input)
      provider = { id: 'new', name: input.name, base_url: input.base_url, scope: input.scope, key_configured: true, key_mask: '****', models: [] }
      return { body: provider }
    }
  })

  await page.setViewportSize({ width: 375, height: 900 })
  await page.goto('models')
  await page.getByRole('button', { name: '添加服务商', exact: true }).click()
  const editor = page.locator('.setting-drawer .t-dialog:visible')
  const save = editor.getByRole('button', { name: '保存并关闭' })
  const template = editor.locator('.t-select')
  const name = editor.getByLabel('服务商名称')
  const address = editor.getByLabel('API 地址')
  const key = editor.getByLabel('API Key')
  await expect(editor.getByRole('heading', { name: '接入配置' })).toBeVisible()
  await expect(save).toBeInViewport()
  await save.click()
  await expect(editor).toContainText('请输入服务商名称。')
  await expect(editor).toContainText('请输入有效的 HTTP 或 HTTPS API 地址。')
  expect(writes).toHaveLength(0)

  const choose = async (label: string) => {
    await template.click()
    await page.locator('.t-select-option:visible').filter({ hasText: label }).click()
  }
  await choose('OpenAI')
  await expect(name).toHaveValue('OpenAI')
  await expect(address).toHaveValue('https://api.openai.com/v1')
  await key.fill('example-key-for-openai')
  await choose('DeepSeek')
  await expect(address).toHaveValue('https://api.deepseek.com')
  await expect(key).toHaveValue('')
  await choose('自定义')
  await expect(name).toHaveValue('')
  await expect(address).toHaveValue('')

  await choose('DeepSeek')
  await name.fill('Enterprise Gateway')
  await address.fill('https://gateway.example.test/v1')
  await key.fill('example-gateway-key')
  await save.click()
  await expect(editor).toHaveCount(0)
  expect(writes).toEqual([{
    name: 'Enterprise Gateway', base_url: 'https://gateway.example.test/v1', api_key: 'example-gateway-key', scope: 'tenant',
  }])

  await page.getByRole('button', { name: '服务商', exact: true }).click()
  await page.getByRole('button', { name: 'Enterprise Gateway · 编辑服务商' }).click()
  await expect(editor).toContainText('编辑企业模型服务商')
  await expect(template).toHaveCount(0)
  await expect(name).toHaveValue('Enterprise Gateway')
  await expect(address).toHaveValue('https://gateway.example.test/v1')
  await expect(key).toHaveValue('')
  await address.fill('https://another.example.test/v1')
  await save.click()
  await expect(editor).toContainText('修改 API 地址需要重新填写 API Key。')
  expect(writes).toHaveLength(1)
  await key.fill('example-new-key')
  await save.click()
  await expect(editor).toHaveCount(0)
  expect(writes[1]).toEqual({
    name: 'Enterprise Gateway', base_url: 'https://another.example.test/v1', api_key: 'example-new-key', scope: 'tenant',
  })
})
