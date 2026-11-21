import assert from 'node:assert/strict'
import test from 'node:test'
import { visibleAdminNavigation } from './navigation'

test('六组侧栏只包含指定入口，组内顺序固定', () => {
  const groups = visibleAdminNavigation('owner', () => true)
  assert.deepEqual(groups.map(({ key, items }) => [key, items.map(item => item.path)]), [
    ['configuration', ['/models', '/knowledge', '/tools', '/agents']],
    ['workspace', ['/enterprise', '/policy']],
    ['integrations', ['/mcp-endpoints', '/channels']],
    ['data_extensions', ['/vector-stores', '/parsers', '/storage', '/sandbox', '/graph-stores']],
    ['permissions', ['/organization', '/members', '/roles']],
    ['system', ['/settings', '/runtime', '/audit']],
  ])
})

test('权限或角色变化后过滤入口和空组，不向自定义角色开放部署专属页', () => {
  const permissions = new Set(['enterprise_kbs:manage'])
  const visible = () => visibleAdminNavigation('custom', permission => permissions.has(permission))
  assert.deepEqual(visible().map(group => group.key), ['configuration', 'data_extensions', 'system'])
  assert.deepEqual(visible()[1]?.items.map(item => item.path), ['/vector-stores', '/storage', '/graph-stores'])
  permissions.clear()
  assert.deepEqual(visible().map(group => group.key), ['system'])
  assert.equal(visibleAdminNavigation('admin', () => true).flatMap(group => group.items).some(item => item.path === '/sandbox'), true)
})
