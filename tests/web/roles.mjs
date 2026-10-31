/** Role management acceptance against deterministic API fixtures: management, assignment and denial. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const json = value => ({ contentType: 'application/json', body: JSON.stringify(value) })
const menus = ['chat', 'agents', 'models', 'audit', 'members', 'roles']
const apis = ['agents:read', 'agents:write', 'roles:manage']
const roles = [{ id: 'role-1', tenant_id: 'tenant', name: '运营', menus: ['agents'], apis: ['agents:read'] }]
const members = [{ tenant_id: 'tenant', user_id: 'member-1', role: 'member', status: 'active' }]
let assigned = []
let manager = true
let assignCalls = 0
await page.route('**/api/v1/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname, method = request.method()
  if (path.endsWith('/tenants')) return route.fulfill(json([{ id: 'tenant', name: '开发空间' }]))
  if (path.endsWith('/me/permissions')) return route.fulfill(json({ menus: manager ? menus : ['chat'], apis: manager ? apis : [] }))
  if (path.endsWith('/permission-catalog')) return route.fulfill(json({ menus, apis }))
  if (path.endsWith('/agents')) return route.fulfill(json([{ id: 'agent-1', name: '研究助手', runtime_type: 'native', published_version_id: null }]))
  if (path.endsWith('/agent-grants')) return route.fulfill(json([]))
  if (path.endsWith('/role-assignments')) return route.fulfill(json(assigned))
  if (path.endsWith('/members') && method === 'GET') return route.fulfill(json(members))
  if (path.endsWith('/roles') && method === 'GET') return route.fulfill(json(roles))
  if (path.includes('/members/member-1/roles/') && method === 'PUT') {
    assignCalls++
    assigned = [{ user_id: 'member-1', role_id: 'role-1' }]
    return route.fulfill({ status: 204, body: '' })
  }
  throw new Error(`Unexpected request: ${method} ${path}`)
})
try {
  await page.goto((process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173') + '/#roles')
  await page.getByRole('heading', { name: '角色与权限', exact: true }).waitFor()
  await page.getByText('菜单：智能体').waitFor()
  await page.locator('.assign-list .el-select').first().click()
  await page.getByRole('option', { name: '运营', exact: true }).click()
  await page.getByText('成员角色已更新', { exact: true }).waitFor()
  assert.equal(assignCalls, 1)
  // A caller without roles:manage sees the denial state and no management data.
  manager = false
  await page.reload()
  await page.getByText('你没有管理角色的权限').waitFor()
  assert.equal(await page.getByRole('heading', { name: '成员角色', exact: true }).count(), 0)
  assert.deepEqual(errors, [])
  console.log('Role management browser acceptance passed (list, assignment, denial).')
} catch (error) {
  console.error(await page.locator('body').innerText())
  throw error
} finally { await browser.close() }
