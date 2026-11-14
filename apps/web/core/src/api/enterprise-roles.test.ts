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
