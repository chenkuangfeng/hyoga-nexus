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
  await expect(page.locator('.parser-group')).toHaveCount(4)
  for (const input of await page.locator('input[type="password"]').all()) await expect(input).toHaveValue('')
  const endpoint = page.locator('.parser-group').first().locator('input').first()
  await endpoint.fill('https://updated.example.test'); await endpoint.blur()
  await page.locator('.parser-actions button').first().click()
  await expect(page.locator('.t-dialog')).toBeVisible(); expect(writes).toHaveLength(0)
  await page.locator('.t-dialog__footer button').last().click()
  await expect(page.locator('.t-alert--success')).toBeVisible()
  expect(writes).toEqual([{ mineru_api_key: '******', mineru_endpoint: 'https://updated.example.test', mineru_enable_table: false }])
  await expectResponsive(page)
})
