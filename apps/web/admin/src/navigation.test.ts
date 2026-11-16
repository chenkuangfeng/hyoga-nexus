import assert from 'node:assert/strict'
import test from 'node:test'
import { visibleAdminNavigation } from './navigation'

test('沿用 WeKnora 分组顺序，所有现有管理路由各保留一个入口', () => {
  const groups = visibleAdminNavigation('owner', () => true)
  assert.deepEqual(groups.map(group => group.key), ['workspace', 'models_runtime', 'integrations', 'data_extensions', 'system_administration', 'platform'])
  const paths = groups.flatMap(group => group.items.map(item => item.path))
  assert.equal(paths.length, new Set(paths).size)
  assert.deepEqual([...paths].sort(), ['/', '/enterprise', '/members', '/organization', '/roles', '/policy', '/agents', '/knowledge', '/usage', '/models', '/wecom', '/channels', '/mcp-endpoints', '/vector-stores', '/parsers', '/storage', '/graph-stores', '/mcp-services', '/tools', '/skill-submissions', '/runtime', '/audit'].sort())
})

test('权限或角色变化后过滤入口和空组，不向自定义角色开放 owner/admin 专属页', () => {
  const permissions = new Set(['enterprise_kbs:manage'])
  const visible = () => visibleAdminNavigation('custom', permission => permissions.has(permission))
  assert.deepEqual(visible().map(group => group.key), ['workspace', 'data_extensions', 'platform'])
  assert.deepEqual(visible()[1]!.items.map(item => item.path), ['/vector-stores', '/storage', '/graph-stores'])
  permissions.clear()
  assert.deepEqual(visible().map(group => group.key), ['platform'])
  assert.equal(visibleAdminNavigation('admin', () => true).flatMap(group => group.items).some(item => item.path === '/enterprise'), false)
})
