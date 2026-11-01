/** Organization acceptance against deterministic API fixtures: admin tree and people, space view, joining from a bound subtree, and non-admin hiding. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const json = value => ({ contentType: 'application/json', body: JSON.stringify(value) })
let isAdmin = true
let joinBody = null
const tree = [
  { id: 'group', parent_id: null, name: '集团', status: 'active', member_count: 0 },
  { id: 'sub', parent_id: 'group', name: '子公司甲', status: 'active', member_count: 1 },
  { id: 'dept', parent_id: 'sub', name: '研发部', status: 'active', member_count: 1 },
]
const people = [{ user_id: 'u-alice', display_name: '张三', units: [{ unit_id: 'dept', unit_name: '研发部', is_primary: true }] }]
const spacePeople = [{ user_id: 'u-alice', display_name: '张三', units: [{ unit_id: 'dept', unit_name: '研发部', is_primary: true }] }]
await page.route('**/api/v1/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
  if (path.endsWith('/auth/me')) return route.fulfill(json({ user_id: 'admin-1', display_name: '管理员', providers: ['password'], is_platform_admin: isAdmin }))
  if (path.endsWith('/tenants')) return route.fulfill(json([{ id: 'tenant', name: '集团空间' }]))
  if (path.endsWith('/me/permissions')) return route.fulfill(json({ menus: ['chat'], apis: ['members:manage'] }))
  if (path.endsWith('/orgs') && method === 'GET') return route.fulfill(json([{ id: 'group', name: '集团', status: 'active', created_at: '2026-11-01T00:00:00Z' }]))
  if (path.endsWith('/orgs/group/tree')) return route.fulfill(json(tree))
  if (path.endsWith('/people') && path.includes('/org-units/')) return route.fulfill(json(path.endsWith('/org-units/dept/people') ? people : []))
  if (path.endsWith('/bindings') && path.includes('/org-units/')) return route.fulfill(json([]))
  if (path.endsWith('/users')) return route.fulfill(json([{ user_id: 'u-bob', display_name: '李四', username: 'lisi' }]))
  if (path.endsWith('/tenants/tenant/organization')) return route.fulfill(json({
    bindings: [{ unit_id: 'sub', unit_name: '子公司甲', organization_name: '集团', status: 'active',
      nodes: [{ id: 'sub', parent_id: null, name: '子公司甲', status: 'active' }, { id: 'dept', parent_id: 'sub', name: '研发部', status: 'active' }] }],
    people: spacePeople,
  }))
  if (path.endsWith('/members/from-organization') && method === 'POST') {
    joinBody = JSON.parse(request.postData() || '{}')
    return route.fulfill(json({ added: ['u-alice'], skipped: [] }))
  }
  throw new Error(`Unexpected request: ${method} ${path}`)
})
try {
  await page.goto((process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173') + '/#orgs')
  await page.getByRole('heading', { name: '组织与人员', exact: true }).waitFor()
  await page.getByRole('button', { name: /^研发部/ }).click()
  await page.getByText('（主节点）').waitFor()
  assert.equal(await page.getByRole('button', { name: /^研发部/ }).getAttribute('aria-pressed'), 'true')

  await page.goto((process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173') + '/#space-org')
  await page.getByRole('heading', { name: '空间组织', exact: true }).waitFor()
  await page.getByRole('heading', { name: '集团 › 子公司甲' }).waitFor()
  await page.getByText('组织人员（1）').waitFor()
  await page.locator('label', { hasText: '张三' }).click()
  await page.getByRole('checkbox', { name: /张三/ }).waitFor({ state: 'attached' })
  assert.equal(await page.getByRole('checkbox', { name: /张三/ }).isChecked(), true)
  await page.getByRole('button', { name: '加入空间（1）' }).waitFor()
  await page.getByRole('button', { name: '加入空间（1）' }).click()
  await page.getByText('已加入 1 人', { exact: true }).waitFor()
  assert.deepEqual(joinBody, { user_ids: ['u-alice'], role: 'member' })

  // A user who is not a platform admin gets no organization-management entry.
  isAdmin = false
  await page.reload()
  await page.getByRole('button', { name: '空间组织', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '组织与人员', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log('Organization browser acceptance passed (admin tree, space view, join, hidden admin entry).')
} catch (error) {
  console.error('Organization acceptance failed:', error.message)
  console.error(await page.locator('body').innerText({ timeout: 2000 }).catch(() => '(page unavailable)'))
  throw error
} finally { await browser.close() }
