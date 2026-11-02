/**
 * Shell layout acceptance across breakpoints: no horizontal overflow at 375/768/1024/1440px,
 * sidebar visibility per breakpoint (drawer below 768px, expanded at 1024px and above).
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const baseURL = process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173'
const json = value => ({ contentType: 'application/json', body: JSON.stringify(value) })
const context = await browser.newContext({ locale: 'zh-CN', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
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
  await page.getByRole('navigation', { name: '主导航' }).waitFor()
  const sidebar = page.locator('#app-sidebar')
  const results = []
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(150)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
    assert.equal(overflow, false, `${width}px: horizontal overflow`)
    const visible = await sidebar.isVisible()
    const box = await sidebar.boundingBox()
    results.push({ width, visible, sidebarWidth: box ? Math.round(box.width) : 0 })
  }
  const at = Object.fromEntries(results.map(r => [r.width, r]))
  // Below 768px the sidebar is a closed drawer; at 1024px and above it is docked.
  assert.equal(at[375].visible, false, '375px: drawer must be closed by default')
  assert.equal(at[1024].visible, true, '1024px: sidebar must be docked')
  assert.equal(at[1440].visible, true, '1440px: sidebar must be docked')
  assert.ok(at[1440].sidebarWidth >= 200, '1440px: expanded sidebar should be at least 200px wide')
  console.log('PASS: no horizontal overflow at 375/768/1024/1440px; drawer below 768px; docked sidebar at 1024px and above')
  console.log(JSON.stringify(results))
} finally { await browser.close() }
