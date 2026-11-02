/**
 * Keyboard acceptance for the app shell: sidebar collapse toggle, narrow-screen drawer
 * (open by button, close with Escape), and the session search palette (filter, arrow
 * selection, Enter to open, Escape to close).
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const baseURL = process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173'
const json = value => ({ contentType: 'application/json', body: JSON.stringify(value) })
const sessions = [
  { id: 's1', title: 'Quarterly report draft', agent_version_id: 'version', updated_at: '2026-11-02T09:00:00Z', org_unit_id: null },
  { id: 's2', title: 'Market research notes', agent_version_id: 'version', updated_at: '2026-11-01T09:00:00Z', org_unit_id: null },
  { id: 's3', title: 'Research follow-up', agent_version_id: 'version', updated_at: '2026-10-30T09:00:00Z', org_unit_id: null },
]
const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
await page.route('**/api/v1/**', async route => {
  const path = new URL(route.request().url()).pathname
  if (path.endsWith('/auth/me')) return route.fulfill(json({ user_id: 'user-1', display_name: 'Tester', providers: ['password'] }))
  if (path.endsWith('/tenants')) return route.fulfill(json([{ id: 'tenant', name: 'Dev space' }]))
  if (path.endsWith('/agents')) return route.fulfill(json([{ id: 'agent', name: 'Research assistant', runtime_type: 'native', published_version_id: 'version' }]))
  if (path.endsWith('/sessions')) return route.fulfill(json(sessions))
  // Opening a session loads an empty message history.
  if (path.endsWith('/messages')) return route.fulfill(json({ messages: [], latest_run: null }))
  if (path.endsWith('/memory-snapshot')) return route.fulfill(json({ exists: false }))
  throw new Error(`Unexpected request: ${path}`)
})
const sidebar = page.locator('#app-sidebar')
try {
  // 1. Desktop: keyboard can reach and activate the collapse toggle.
  await page.goto(baseURL + '/chat')
  await page.getByRole('navigation', { name: 'Main navigation' }).waitFor()
  const collapse = page.getByRole('button', { name: /Collapse sidebar|Expand sidebar/ })
  const before = await collapse.getAttribute('aria-expanded')
  await collapse.focus()
  await page.keyboard.press('Enter')
  await page.waitForTimeout(150)
  assert.notEqual(await collapse.getAttribute('aria-expanded'), before, 'Enter must toggle the sidebar')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(150)
  assert.equal(await collapse.getAttribute('aria-expanded'), before, 'second Enter must restore the sidebar')

  // 2. Session search palette: open with the search button, filter, move, open with Enter.
  await page.getByRole('button', { name: 'Search', exact: true }).first().click()
  const input = page.locator('#session-search-input')
  await input.waitFor()
  await page.waitForFunction(() => document.activeElement?.id === 'session-search-input', null, { timeout: 2000 })
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'session-search-input', 'search input must receive focus')
  await page.keyboard.type('research')
  const options = page.getByRole('option')
  assert.equal(await options.count(), 2, 'filter must keep the two matching sessions')
  assert.equal(await input.getAttribute('aria-activedescendant'), 'session-search-s2')
  await page.keyboard.press('ArrowDown')
  assert.equal(await input.getAttribute('aria-activedescendant'), 'session-search-s3')
  await page.keyboard.press('ArrowDown') // wraps to the first match
  assert.equal(await input.getAttribute('aria-activedescendant'), 'session-search-s2')
  await page.keyboard.press('ArrowUp') // wraps back to the last match
  assert.equal(await input.getAttribute('aria-activedescendant'), 'session-search-s3')
  await page.keyboard.press('Enter')
  await page.waitForURL(/\/chat\/s3$/)
  await page.locator('#session-search-input').waitFor({ state: 'hidden', timeout: 2000 })

  // 3. Escape closes the palette without opening anything.
  await page.getByRole('button', { name: 'Search', exact: true }).first().click()
  await page.locator('#session-search-input').waitFor()
  await page.keyboard.press('Escape')
  await page.locator('#session-search-input').waitFor({ state: 'hidden', timeout: 2000 })
  assert.match(page.url(), /\/chat\/s3$/, 'Escape must not open a session')

  // 4. Narrow screen: the menu button opens the drawer; Escape closes it.
  await page.setViewportSize({ width: 375, height: 900 })
  await page.waitForTimeout(150)
  assert.equal(await sidebar.isVisible(), false, 'drawer must start closed')
  const menu = page.getByRole('button', { name: 'Open navigation' })
  await menu.focus()
  await page.keyboard.press('Enter')
  await page.waitForTimeout(150)
  assert.equal(await sidebar.isVisible(), true, 'Enter on the menu button must open the drawer')
  assert.equal(await menu.getAttribute('aria-expanded'), 'true')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(150)
  assert.equal(await sidebar.isVisible(), false, 'Escape must close the drawer')
  assert.equal(await menu.getAttribute('aria-expanded'), 'false')

  console.log('PASS: keyboard collapse toggle, search palette (focus, filter, arrow wrap, Enter opens, Escape closes), narrow drawer open/close')
} finally { await browser.close() }
