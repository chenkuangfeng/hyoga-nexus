import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { runInNewContext } from 'node:vm'

function setup(response: unknown) {
  const calls: Array<{ verb: string; url: string; input: unknown }> = []
  const request = (verb: string) => async (url: string, input?: unknown) => { calls.push({ verb, url, input }); return response }
  const exports: Record<string, any> = {}
  runInNewContext(ts.transpileModule(readFileSync(new URL('./enterprise-admin.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
    exports, require: (name: string) => { assert.equal(name, '../utils/request'); return { get: request('GET'), patch: request('PATCH') } },
  })
  return { api: exports, calls }
}
const policy = { self_build_agents: 'org_units', self_build_org_unit_ids: ['department'], personal_models: false, external_sharing: true, personal_wecom_channels: 'review', personal_external_channels: true, retention_days: 7 }

test('策略接口限定企业路径，用 PATCH 显式传递 null；部门显示名称并提交稳定 ID', async () => {
  const s = setup(policy)
  await s.api.getEnterprisePolicy('tenant/a')
  assert.equal(s.calls[0].url, '/api/v1/tenants/tenant%2Fa/admin/policy')
  await s.api.updateEnterprisePolicy('tenant/a', { retention_days: null })
  assert.equal(s.calls[1].verb, 'PATCH')
  assert.deepEqual(s.calls[1].input, { retention_days: null })
  const org = setup([{ id: 'department', parent_id: null, name: '研发部', status: 'active' }])
  const rows = await org.api.listPolicyDepartments('tenant/a')
  assert.equal(rows[0].name, '研发部')
  assert.equal(org.calls[0].url, '/api/v1/tenants/tenant%2Fa/admin/org-units/tree')
})

test('错误的布尔值、枚举及保留天数不得作为可编辑策略消费', () => {
  const { api } = setup(null)
  for (const invalid of [{ ...policy, personal_models: 'false' }, { ...policy, self_build_agents: 'invalid' }, { ...policy, retention_days: 0 }, { ...policy, retention_days: 1.5 }, { ...policy, retention_days: 3651 }, { ...policy, retention_days: undefined }]) assert.throws(() => api.policyFromResponse(invalid), /admin_response_invalid/)
  assert.equal(api.policyFromResponse({ ...policy, retention_days: null }).retention_days, null)
})

test('策略补丁不覆盖未修改字段，部门顺序不构成变化', () => {
  const { api } = setup(null)
  const before = { ...policy, self_build_org_unit_ids: ['b', 'a'] }
  const unchanged = api.policyChanges(before, { ...before, self_build_org_unit_ids: ['a', 'b'] })
  assert.equal(Object.keys(unchanged).length, 0)
  const changed = api.policyChanges(policy, { ...policy, retention_days: null })
  assert.deepEqual(JSON.parse(JSON.stringify(changed)), { retention_days: null })
})
