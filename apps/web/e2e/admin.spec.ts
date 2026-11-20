import { test, expect, expectResponsive } from './fixtures'

test('管理应用登录入口独立且可在手机宽度使用', async ({ page }) => {
  await page.goto('login')
  await expect(page.locator('input[type="password"]')).toBeVisible()
  await expect(page).toHaveURL(/\/admin\/login$/)
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
  await expect(page.locator('.nav-group-title')).toHaveText(['企业', '知识库', '发布集成', '数据和扩展', '权限', '系统'])
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

test('分组菜单保留权限入口，折叠后仍可通过图标名称访问', async ({ page, api }, testInfo) => {
  await api.signIn()
  api.handle(request => new URL(request.url()).pathname === '/api/v1/tenants/a/me/permissions'
    ? { body: { apis: ['org:manage', 'members:manage', 'roles:manage', 'models:manage', 'tools:manage', 'enterprise_kbs:manage', 'enterprise_agents:manage', 'audit:read', 'policy:manage'] } } : undefined)
  await page.goto('')
  const navigation = page.locator('#admin-navigation')
  await expect(navigation.locator('.nav-group-title')).toHaveText(['企业', '智能体', '知识库', '模型', '发布集成', '数据和扩展', '工具箱', '权限', '系统'])
  await expect(navigation.locator('a')).toHaveCount(20)
  await page.screenshot({ path: testInfo.outputPath('grouped-navigation.png') })
  const labels = await navigation.locator('a').allTextContents()
  expect(labels.filter(label => label.includes('企业'))).toEqual(['企业空间', '企业策略', '企业组织', '企业微信'])
  await page.getByRole('button', { name: '收起侧边栏' }).click()
  await expect(navigation.locator('.nav-group-title')).toHaveCount(0)
  await expect(navigation.getByRole('link', { name: '解析引擎' })).toHaveAttribute('title', '解析引擎')
  await page.getByRole('button', { name: '展开侧边栏' }).focus()
  await page.keyboard.press('Enter')
  await expect(navigation.locator('.nav-group-title')).toHaveCount(9)
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
  const navigation = page.locator('#admin-navigation')
  const storageLink = navigation.locator('a[href$="/storage"]')
  await storageLink.evaluate(element => element.setAttribute('data-e2e-original', 'true'))
  delayPermissions = true
  const permissionRequest = page.waitForRequest(request => new URL(request.url()).pathname === permissionsPath)
  try {
    await storageLink.focus()
    await page.keyboard.press('Enter')
    await permissionRequest
    await expect(storageLink).toBeFocused()
    await expect(page).toHaveURL(/\/admin\/settings$/)
  } finally {
    releasePermissions()
  }
  await expect(page).toHaveURL(/\/admin\/storage$/)
  await expect(page.locator('.backend-card--add')).toBeVisible()
  await expect(storageLink).toHaveAttribute('data-e2e-original', 'true')
  await page.goBack()
  await expect(page).toHaveURL(/\/admin\/settings$/)
  await expect(storageLink).toHaveAttribute('data-e2e-original', 'true')
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
  const selectMode = async (label: string) => {
    await page.locator('.setting-row').filter({ hasText: '二级编辑界面' }).locator('.t-select').click()
    await page.locator('.t-select-option:visible').filter({ hasText: label }).click()
  }
  await selectMode('抽屉')
  await page.locator('#admin-navigation').getByRole('link', { name: '模型管理', exact: true }).click()
  await page.getByRole('button', { name: '添加服务商', exact: true }).click()
  await expect(page.locator('.t-drawer--open')).toBeVisible()
  await page.locator('.t-drawer--open .t-drawer__close-btn').click()
  await page.locator('#admin-navigation').getByRole('link', { name: '系统设置', exact: true }).click()
  await selectMode('替换路由')
  await page.locator('#admin-navigation').getByRole('link', { name: '模型管理', exact: true }).click()
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
  api.handle(request => {
    const path = new URL(request.url()).pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: ['enterprise_kbs:manage', 'enterprise_agents:manage', 'tools:manage'] } }
    if (path === '/api/v1/tenants/a/admin/knowledge/bases') return { body: { items: [{ id: 'kb1', tenant_id: 'a', ownership: 'enterprise', shared: false, name: 'Knowledge reference', description: 'Knowledge content', type: 'document', visibility: 'tenant', knowledge_count: 3, can_manage: true }] } }
    if (path === '/api/v1/tenants/a/admin/agents') return { body: [{ id: 'agent1', tenant_id: 'a', ownership: 'enterprise', can_maintain: true, name: 'Agent reference', description: 'Agent content', status: 'draft', runtime_type: 'native', instructions: '', published_version_id: null, model_profile_version_id: null, version_counter: 0, budgets: {}, resource_bindings: [], created_at: '2026-11-18', updated_at: '2026-11-18' }] }
    if (path === '/api/v1/tenants/a/skills') return { body: [{ name: 'Skill reference', source: 'builtin', scope: 'builtin', source_tenant_id: 'a', version: 1, version_id: 'v1', tools: [], execution: 'sandbox', model_invocable: true, description: 'Skill content', disabled: false }] }
    if (path === '/api/v1/tenants/a/mcp-services') return { body: [{ id: 'm1', tenant_id: 'a', name: 'MCP reference', description: 'MCP content', transport: 'streamable_http', config: { url: 'https://mcp.example.test' }, enabled: true, config_epoch: 'e1', created_by: 'u', created_at: '2026-11-18', updated_at: '2026-11-18' }] }
  })
  await page.goto('knowledge')
  await expect(page.locator('.resource-directory-card')).toContainText('Knowledge reference')
  await page.locator('#admin-navigation').getByRole('link', { name: '智能体管理' }).click()
  await expect(page.locator('.resource-directory-card')).toContainText('Agent reference')
  await page.locator('#admin-navigation').getByRole('link', { name: '技能管理' }).click()
  await expect(page.locator('.skill-card')).toContainText('Skill reference')
  await page.locator('#admin-navigation').getByRole('link', { name: 'MCP服务注册' }).click()
  await expect(page.locator('.service-card')).toContainText('MCP reference')
  await expect(page.locator('#admin-navigation').getByRole('link', { name: 'MCP服务发布' })).toHaveAttribute('href', /mcp-endpoints$/)
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
