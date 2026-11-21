import assert from 'node:assert/strict'
import test from 'node:test'
import { entriesForTenant } from './entries.ts'

test('切换企业时不沿用上一企业的管理入口', () => {
  const memberships = [
    { tenant_id: 'a', role: 'owner', entries: ['workspace', 'enterprise'] as const },
    { tenant_id: 'b', role: 'contributor', entries: ['workspace'] as const },
  ].map(row => ({ ...row, entries: [...row.entries] }))
  assert.deepEqual(entriesForTenant(memberships, 'a'), ['workspace', 'enterprise'])
  assert.deepEqual(entriesForTenant(memberships, 'b'), ['workspace'])
  assert.deepEqual(entriesForTenant(memberships, 'removed'), [])
})
test('旧缓存缺失 entries 时不根据角色推断管理权限', () => {
  assert.deepEqual(entriesForTenant([{ tenant_id: 'a', role: 'owner' }], 'a'), [])
})
