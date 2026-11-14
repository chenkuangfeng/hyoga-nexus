import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'

test('角色响应拒绝跨企业数据、缺失权限与错误内置标记', t => {
  const api = fixture(t).evaluate(readFileSync(new URL('./enterprise-roles.ts', import.meta.url), 'utf8'), { '../utils/request': {} })
  const row = { id: 'r', tenant_id: 'a', name: 'Role', builtin: true, menus: [], apis: ['roles:manage'] }
  assert.equal(api.roleFromResponse(row, 'a').builtin, true)
  assert.throws(() => api.roleFromResponse(row, 'b'), /roles_response_invalid/)
  assert.throws(() => api.roleFromResponse({ ...row, builtin: 'true' }, 'a'), /roles_response_invalid/)
  assert.throws(() => api.permissionsFromResponse({ menus: [] }), /roles_response_invalid/)
})

test('部门分配使用真实端点与 role_id，并拒绝重叠或错误类型的结果计数', async t => {
  let response: unknown = { assigned: ['a'], skipped: ['b'] }
  const calls: Array<{ url: string; input: unknown }> = []
  const api = fixture(t).evaluate(readFileSync(new URL('./enterprise-roles.ts', import.meta.url), 'utf8'), {
    '../utils/request': { post: async (url: string, input: unknown) => { calls.push({ url, input }); return response } },
  })
  const result = await api.assignDepartmentRole('tenant', 'dept', 'role')
  assert.equal(result.assigned.length, 1); assert.equal(result.skipped.length, 1)
  assert.equal(calls[0].url, '/api/v1/tenants/tenant/org-units/dept/role-assignments')
  assert.equal((calls[0].input as { role_id: string }).role_id, 'role')
  response = { assigned: ['a'], skipped: ['a'] }
  await assert.rejects(api.assignDepartmentRole('tenant', 'dept', 'role'), /roles_response_invalid/)
  response = { assigned: 3, skipped: [] }
  await assert.rejects(api.assignDepartmentRole('tenant', 'dept', 'role'), /roles_response_invalid/)
})
