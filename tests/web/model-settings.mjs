/** Settings interaction acceptance against deterministic API fixtures. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ locale: 'zh-CN', viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
let providers = [], defaults = {}, tested = 0, created = 0, saved = 0
const json = value => ({ contentType: 'application/json', body: JSON.stringify(value) })
await page.route('**/api/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
  if (new URL(request.url()).pathname.endsWith('/auth/me')) return route.fulfill(json({ user_id: 'user-1', display_name: '测试用户', providers: ['password'] }))
  if (path.endsWith('/tenants')) return route.fulfill(json([{ id: 'tenant', name: '开发空间' }]))
  if (path.endsWith('/model-settings')) return route.fulfill(json({ providers, defaults, can_manage_tenant: true }))
  if (path.endsWith('/providers') && method === 'POST') {
    saved++
    const value = request.postDataJSON()
    assert.equal(value.api_key, 'private-browser-test-key')
    const provider = { id: 'provider-' + saved, name: value.name, base_url: value.base_url, scope: value.scope, key_configured: true, models: [] }
    providers.push(provider)
    return route.fulfill(json(provider))
  }
  if (path.endsWith('/models') && method === 'POST') {
    const model = { id: 'model-1', name: request.postDataJSON().name, version: 1, version_id: 'version-1' }
    providers[0].models.push(model)
    return route.fulfill(json({ id: model.id, version_id: model.version_id }))
  }
  if (path.endsWith('/default')) {
    const body = request.postDataJSON(); defaults[body.scope] = body.version_id
    return route.fulfill(json({ status: 'saved' }))
  }
  if (path.endsWith('/test')) { tested++; return route.fulfill(json({ ok: true, message: '连接成功，流式响应正常' })) }
  if (path.endsWith('/agents')) { created++; return route.fulfill(json({ published_version_id: 'agent-version' })) }
  if (path.endsWith('/providers/provider-1') && method === 'DELETE') { providers = []; defaults = {}; return route.fulfill(json({ status: 'disabled' })) }
  if (path.endsWith('/sessions')) return route.fulfill(json([]))
  throw new Error(`Unexpected request: ${method} ${path}`)
})
try {
  await page.goto((process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173') + '/space/models')
  await page.getByRole('heading', { name: '模型供应商', exact: true }).waitFor()
  await page.getByRole('button', { name: '添加供应商', exact: true }).click()
  await page.locator('#provider-name').fill('个人供应商')
  await page.locator('#provider-url').fill('https://public.example/v1')
  await page.locator('#provider-key').fill('private-browser-test-key')
  await page.getByRole('button', { name: '保存供应商', exact: true }).click()
  await page.getByRole('heading', { name: /个人供应商/ }).waitFor()
  assert.equal(saved, 1)
  assert.equal(await page.locator('body').innerText().then(text => text.includes('private-browser-test-key')), false)
  assert.equal(await page.evaluate(() => JSON.stringify(localStorage).includes('private-browser-test-key')), false)
  await page.getByRole('button', { name: '添加模型', exact: true }).click()
  await page.locator('#provider-model-name').fill('model-test')
  await page.getByRole('button', { name: '保存模型', exact: true }).click()
  await page.getByText('模型已保存', { exact: true }).waitFor()
  await page.locator('#personal-default').focus()
  await page.keyboard.press('ArrowDown')
  await page.getByRole('option', { name: '个人供应商 / model-test', exact: true }).click()
  await page.getByText('默认模型已更新', { exact: true }).waitFor()
  assert.equal(defaults.personal, 'version-1')
  await page.getByRole('button', { name: '测试 model-test', exact: true }).click()
  await page.getByText('连接成功，流式响应正常', { exact: true }).waitFor()
  assert.equal(tested, 1)
  await page.locator('#settings-agent-name').fill('对话助手')
  await page.getByRole('button', { name: '创建并发布', exact: true }).click()
  await page.getByText('智能体已发布，可以返回对话工作台新建会话', { exact: true }).waitFor()
  assert.equal(created, 1)
  await page.getByRole('button', { name: '编辑供应商', exact: true }).click()
  assert.equal(await page.locator('#provider-key').inputValue(), '')
  await page.locator('#provider-key').fill('discarded-key')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '编辑供应商', exact: true }).click()
  assert.equal(await page.locator('#provider-key').inputValue(), '')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.setViewportSize({ width: 375, height: 900 })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  await page.getByRole('button', { name: '停用供应商', exact: true }).click()
  await page.getByRole('button', { name: '停用', exact: true }).click()
  await page.getByText('已停用', { exact: true }).waitFor()
  assert.deepEqual(defaults, {})
  await page.keyboard.press('Tab')
  assert.ok(await page.evaluate(() => document.activeElement !== document.body))
  assert.deepEqual(errors, [])
  console.log('Settings browser acceptance passed (1440px/375px, defaults, write-only key, testing, publishing, disabling).')
} catch (error) {
  console.error(await page.locator('body').innerText())
  throw error
} finally { await browser.close() }
