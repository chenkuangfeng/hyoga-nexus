import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  toLevel, toNexusShareBody, toOrganizationList, toWeKnoraShare, toWeKnoraShareList, toWeKnoraSharedBase,
} from './nexusKnowledgeShares.ts'

test('levels outside viewer/editor/admin fall back to viewer', () => {
  assert.equal(toLevel('admin'), 'admin')
  assert.equal(toLevel('owner'), 'viewer')
  assert.equal(toLevel(undefined), 'viewer')
})

test('share request maps the organization to a shared space and the permission to a level', () => {
  assert.deepEqual(toNexusShareBody({ organization_id: 's1', permission: 'editor' }), { shared_space_id: 's1', level: 'editor' })
  assert.deepEqual(toNexusShareBody({ organization_id: 's1', permission: 'bogus' }), { shared_space_id: 's1', level: 'viewer' })
})

test('a share is keyed by its shared space id so removal and level change can address it', () => {
  const share = toWeKnoraShare({
    id: 'g1', kb_id: 'k1', shared_space_id: 's1', shared_space_name: '联盟', level: 'admin',
    owner_tenant_id: 't1', created_at: '2026-11-11T00:00:00Z',
  }, 'k0')
  assert.equal(share.id, 's1')
  assert.equal(share.organization_id, 's1')
  assert.equal(share.organization_name, '联盟')
  assert.equal(share.knowledge_base_id, 'k1')
  assert.equal(share.permission, 'admin')
  assert.equal(toWeKnoraShare({}, 'k0').knowledge_base_id, 'k0')
})

test('share list tolerates a missing array', () => {
  assert.deepEqual(toWeKnoraShareList(undefined, 'k'), { shares: [], total: 0 })
  assert.equal(toWeKnoraShareList([{ shared_space_id: 'a' }, { shared_space_id: 'b' }], 'k').total, 2)
})

test('a base shared with me carries the owner space name and the effective level', () => {
  const row = toWeKnoraSharedBase({
    id: 'k1', name: '手册', description: 'd', type: 'faq', level: 'editor',
    owner_tenant_id: 't1', owner_tenant_name: 'Acme', knowledge_count: 3, updated_at: 'u',
  })
  assert.equal(row.knowledge_base.id, 'k1')
  assert.equal(row.knowledge_base.type, 'faq')
  assert.equal(row.org_name, 'Acme')
  assert.equal(row.permission, 'editor')
  assert.equal(row.source_tenant_id, 't1')
})

test('shared spaces become the organizations the share dialog offers', () => {
  const list = toOrganizationList([{ id: 's1', name: '联盟', role: 'viewer', owner_tenant_id: 't1', member_count: 2 }])
  assert.equal(list.total, 1)
  assert.equal(list.organizations[0].id, 's1')
  assert.equal(list.organizations[0].is_owner, true)
  assert.equal(list.organizations[0].my_role, 'viewer')
  assert.deepEqual(toOrganizationList(null), { organizations: [], total: 0 })
})
