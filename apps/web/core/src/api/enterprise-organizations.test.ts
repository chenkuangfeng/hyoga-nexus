import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
function setup(response: unknown) {
  const calls: Array<{ verb: string; url: string; input: unknown }> = []
  const request = (verb: string) => async (url: string, input?: unknown) => { calls.push({ verb, url, input }); return response }
  const exports: Record<string, any> = {}
  runInNewContext(ts.transpileModule(readFileSync(new URL('./enterprise-organizations.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports, require: (name: string) => { assert.equal(name, '../utils/request'); return { get: request('GET'), post: request('POST'), patch: request('PATCH'), put: request('PUT'), del: request('DELETE') } } })
  return { api: exports, calls }
}
const root = { id: 'root', parent_id: null, name: '公司', status: 'active', source: 'manual', member_count: 0 }
const child = { ...root, id: 'child/a', parent_id: 'root', name: '研发' }
const detail = { ...child, tenant_id: 'tenant/a', root_id: 'root' }

test('组织树拒绝重复根、缺失父节点、环、错误来源与成员数，不把错误响应当空树', async () => {
  const { api } = setup(null)
  assert.equal(api.organizationTreeFromResponse([]).length, 0)
  assert.equal(api.organizationTreeFromResponse([root, child]).length, 2)
  for (const bad of [null, {}, [root, root], [root, { ...child, parent_id: null }], [root, { ...child, parent_id: 'missing' }], [root, { ...child, parent_id: 'second' }, { ...child, id: 'second', parent_id: 'child/a' }], [{ ...root, source: 'unknown' }], [{ ...root, member_count: '0' }], [{ ...root, member_count: -1 }]]) assert.throws(() => api.organizationTreeFromResponse(bad), /organization_response_invalid/)
  const deep = [root, ...Array.from({ length: 12000 }, (_, index) => ({ ...child, id: `n${index}`, parent_id: index ? `n${index - 1}` : 'root' }))]
  assert.equal(api.organizationTreeFromResponse(deep).length, 12001)
})
test('创建根不传父节点，子节点与修改回执限定企业、节点和父节点', async () => {
  const roots = setup({ ...root, tenant_id: 'tenant/a', root_id: 'root' })
  await roots.api.createOrganizationUnit('tenant/a', { name: '公司' })
  assert.equal(roots.calls[0].url, '/api/v1/tenants/tenant%2Fa/org-units')
  assert.equal(Object.hasOwn(roots.calls[0].input as object, 'parent_id'), false)
  const s = setup(detail); await s.api.updateOrganizationUnit('tenant/a', 'child/a', { name: '新名称' })
  assert.equal(s.calls[0].verb, 'PATCH'); assert.equal(s.calls[0].url, '/api/v1/tenants/tenant%2Fa/org-units/child%2Fa')
  await assert.rejects(setup({ ...detail, tenant_id: 'other' }).api.updateOrganizationUnit('tenant/a', 'child/a', {}), /organization_response_invalid/)
  await assert.rejects(setup({ ...detail, id: 'wrong' }).api.updateOrganizationUnit('tenant/a', 'child/a', {}), /organization_response_invalid/)
  await assert.rejects(setup(detail).api.createOrganizationUnit('tenant/a', { name: '研发', parent_id: 'wrong' }), /organization_response_invalid/)
})
test('成员归属读取校验布尔值与重复人员；首次归属可由服务端自动设为主部门', async () => {
  const member = { user_id: 'person/a', display_name: '成员', is_primary: true }
  const s = setup([member]); await s.api.listOrganizationMembers('tenant/a', 'child/a')
  assert.equal(s.calls[0].url, '/api/v1/tenants/tenant%2Fa/org-units/child%2Fa/members')
  await assert.rejects(setup([{ ...member, is_primary: 'false' }]).api.listOrganizationMembers('tenant/a', 'child/a'), /organization_response_invalid/)
  await assert.rejects(setup([member, member]).api.listOrganizationMembers('tenant/a', 'child/a'), /organization_response_invalid/)
  const assign = setup({ user_id: 'person/a', unit_id: 'child/a', is_primary: true })
  assert.equal((await assign.api.assignOrganizationMember('tenant/a', 'child/a', 'person/a', false)).is_primary, true)
  assert.equal(assign.calls[0].verb, 'PUT'); assert.deepEqual(JSON.parse(JSON.stringify(assign.calls[0].input)), { is_primary: false })
  await assign.api.removeOrganizationMember('tenant/a', 'child/a', 'person/a')
  assert.equal(assign.calls[1].verb, 'DELETE'); assert.equal(assign.calls[1].url, '/api/v1/tenants/tenant%2Fa/org-units/child%2Fa/members/person%2Fa')
  await assert.rejects(setup({ user_id: 'wrong', unit_id: 'child/a', is_primary: true }).api.assignOrganizationMember('tenant/a', 'child/a', 'person/a', true), /organization_response_invalid/)
})
