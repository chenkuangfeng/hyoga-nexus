import assert from 'node:assert/strict'
import test from 'node:test'
import { visibleAdminNavigation } from './navigation'

test('沿用 WeKnora 分组顺序，所有现有管理路由各保留一个入口', () => {
  const groups = visibleAdminNavigation('owner', () => true)
  assert.deepEqual(groups.map(group => group.key), ['resources', 'account', 'workspace', 'models_runtime', 'integrations', 'data_extensions', 'system_administration'])
  const paths = groups.flatMap(group => group.items.map(item => item.path))
  assert.equal(paths.length, new Set(paths).size)
  assert.deepEqual(groups.find(group => group.key === 'integrations')?.items.map(item => item.path), ['/channels', '/mcp-endpoints', '/wecom'])

})

test('权限或角色变化后过滤入口和空组，不向自定义角色开放 owner/admin 专属页', () => {
  const permissions = new Set(['enterprise_kbs:manage'])
  const visible = () => visibleAdminNavigation('custom', permission => permissions.has(permission))
  assert.deepEqual(visible().map(group => group.key), ['resources', 'account', 'data_extensions'])
  assert.deepEqual(visible()[2]!.items.map(item => item.path), ['/vector-stores', '/storage', '/graph-stores'])
  permissions.clear()
  assert.deepEqual(visible().map(group => group.key), ['account'])
  assert.equal(visibleAdminNavigation('admin', () => true).flatMap(group => group.items).some(item => item.path === '/enterprise'), true)
})
