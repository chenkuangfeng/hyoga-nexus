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
  await expect(page.locator('.nav-group-title')).toHaveText(['空间', '发布集成', '数据与扩展', '系统管理', '平台'])
  await page.locator('.engine-card').first().click()
  await expect(page.locator('.setting-drawer')).toBeVisible()
  await expect(page.locator('.parser-group')).toHaveCount(1)
  for (const input of await page.locator('input[type="password"]').all()) await expect(input).toHaveValue('')
  const endpoint = page.locator('.parser-group').first().locator('input').first()
  await endpoint.fill('https://updated.example.test'); await endpoint.blur()
  await page.locator('.setting-drawer__footer-right button').last().click()
  await expect(page.locator('.t-dialog')).toBeVisible(); expect(writes).toHaveLength(0)
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
  await expect(navigation.locator('.nav-group-title')).toHaveText(['空间', '模型', '发布集成', '数据与扩展', '系统管理', '平台'])
  await expect(navigation.locator('a')).toHaveCount(22)
  await page.screenshot({ path: testInfo.outputPath('grouped-navigation.png') })
  const labels = await navigation.locator('a').allTextContents()
  expect(labels.filter(label => label.includes('企业'))).toEqual(['企业微信'])
  await page.getByRole('button', { name: '收起侧边栏' }).click()
  await expect(navigation.locator('.nav-group-title')).toHaveCount(0)
  await expect(navigation.getByRole('link', { name: '解析引擎' })).toHaveAttribute('title', '解析引擎')
  await page.getByRole('button', { name: '展开侧边栏' }).focus()
  await page.keyboard.press('Enter')
  await expect(navigation.locator('.nav-group-title')).toHaveCount(6)
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
  await expect(page.locator('.setting-drawer')).toHaveCount(0)
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
