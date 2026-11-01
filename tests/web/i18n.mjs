/** Interface language smoke test: English sidebar and settings, then switching back to Chinese. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const baseURL = process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173'
const page = await browser.newPage({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
const json = value => ({ contentType: 'application/json', body: JSON.stringify(value) })
await page.route('**/api/v1/**', async route => {
  const path = new URL(route.request().url()).pathname
  if (path.endsWith('/auth/me')) return route.fulfill(json({ user_id: 'user-1', display_name: 'Tester', providers: ['password'] }))
  if (path.endsWith('/tenants')) return route.fulfill(json([{ id: 'tenant', name: 'Dev space' }]))
  if (path.endsWith('/agents')) return route.fulfill(json([{ id: 'agent', name: 'Research assistant', runtime_type: 'native', published_version_id: 'version' }]))
  if (path.endsWith('/sessions')) return route.fulfill(json([]))
  throw new Error(`Unexpected request: ${path}`)
})
try {
  await page.goto(baseURL + '/chat')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.waitFor()
  assert.equal(await page.getByRole('button', { name: 'New chat', exact: true }).count(), 1)
  const navText = await nav.innerText()
  assert.doesNotMatch(navText, /[一-鿿]/, 'English sidebar must not contain Chinese labels')
  assert.equal(await page.locator('html').getAttribute('lang'), 'en-US')
  // Switch to Chinese from the user menu; the choice applies immediately and is remembered.
  await page.locator('.user-button').click()
  await page.getByRole('menuitem', { name: '简体中文' }).click()
  await page.getByRole('button', { name: '新对话', exact: true }).waitFor()
  assert.equal(await page.evaluate(() => localStorage.getItem('nexus_locale')), 'zh-CN')
  console.log('PASS: English sidebar labels, document language, switching to Chinese and remembering the choice')
} finally { await browser.close() }
