/** Sign-in acceptance: unauthenticated redirect to the login page, password sign-in, and the CSRF header. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ locale: 'zh-CN', viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const json = (value, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(value) })
let signedIn = false, loginHeaders = null, loginCalls = 0
await page.route('**/api/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
  if (path.endsWith('/auth/me')) return signedIn
    ? route.fulfill(json({ user_id: 'user-1', display_name: '测试用户', providers: ['password'] }))
    : route.fulfill(json({ error: { code: 'unauthorized', message: 'Sign in is required' } }, 401))
  if (path.endsWith('/auth/login') && method === 'POST') {
    loginCalls++
    loginHeaders = request.headers()
    const { username, password } = request.postDataJSON()
    if (username === 'alice' && password === 'correct-password-1') { signedIn = true; return route.fulfill({ status: 204, body: '' }) }
    return route.fulfill(json({ error: { code: 'unauthorized', message: '用户名或密码错误' } }, 401))
  }
  if (path.endsWith('/tenants')) return route.fulfill(json([{ id: 'tenant', name: '开发空间' }]))
  if (path.endsWith('/agents')) return route.fulfill(json([]))
  if (path.endsWith('/sessions')) return route.fulfill(json([]))
  if (path.endsWith('/capabilities')) return route.fulfill(json({}))
  throw new Error(`Unexpected request: ${method} ${path}`)
})
try {
  await page.goto((process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173') + '/chat')
  await page.getByRole('heading', { name: '登录', exact: true }).waitFor()
  assert.equal(await page.getByRole('navigation', { name: '主导航' }).count(), 0)
  assert.equal(await page.getByRole('link', { name: '使用企业微信扫码登录' }).getAttribute('href'), '/api/v1/auth/wecom/start')
  await page.getByLabel('账号', { exact: true }).fill('alice')
  await page.getByLabel('密码', { exact: true }).fill('wrong-password-value')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByText('用户名或密码错误').waitFor()
  await page.getByLabel('密码', { exact: true }).fill('correct-password-1')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('navigation', { name: '主导航' }).waitFor()
  assert.equal(loginCalls, 2)
  assert.equal(loginHeaders['x-nexus-request'], '1', 'login must carry the CSRF header')
  assert.equal(await page.getByLabel('密码', { exact: true }).count(), 0, 'password field must be cleared after the page changes')
  assert.deepEqual(errors, [])
  console.log('Sign-in browser acceptance passed (redirect, failure message, password sign-in, CSRF header).')
} catch (error) {
  console.error(await page.locator('body').innerText())
  throw error
} finally { await browser.close() }
