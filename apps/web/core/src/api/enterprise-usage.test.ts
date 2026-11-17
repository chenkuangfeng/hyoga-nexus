import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'
const source = readFileSync(new URL('./enterprise-usage.ts', import.meta.url), 'utf8')

test('闭区间日期与查询参数使用已有管理端路径，无效日期不发送请求', async t => {
  const calls: unknown[][] = []
  const api = fixture(t).evaluate(source, { '../utils/request': { get: async (...args: unknown[]) => { calls.push(args); return { items: [] } } } })
  await api.getEnterpriseUsage('a/b', 'day', '2024-02-29', '2024-02-29')
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['/api/v1/tenants/a%2Fb/admin/usage', { params: { group_by: 'day', start: '2024-02-29', end: '2024-02-29' } }]])
  for (const [start, end] of [['2026-02-29', '2026-03-01'], ['2026-11-20', '2026-11-01'], ['2026-1-1', '2026-11-01']]) await assert.rejects(api.getEnterpriseUsage('a', 'day', start, end), /usage_dates_invalid/)
  assert.equal(calls.length, 1)
})

test('用量响应拒绝缺失、负数、小数与不安全整数，不把错误响应当空报表', async t => {
  const valid = { key: '2026-11-01', runs: 1, input_tokens: 0, output_tokens: 10, cache_read_tokens: 50, cache_creation_tokens: 20 }
  let response: unknown = { items: [valid] }
  const api = fixture(t).evaluate(source, { '../utils/request': { get: async () => response } })
  assert.equal((await api.getEnterpriseUsage('a', 'day', '2026-11-01', '2026-11-01'))[0].input_tokens, 0)
  for (const value of [-1, 1.1, Number.MAX_SAFE_INTEGER + 1, '3', undefined]) {
    response = { items: [{ ...valid, input_tokens: value }] }
    await assert.rejects(api.getEnterpriseUsage('a', 'day', '2026-11-01', '2026-11-01'), /usage_response_invalid/)
  }
  response = { error: 'unavailable' }
  await assert.rejects(api.getEnterpriseUsage('a', 'day', '2026-11-01', '2026-11-01'), /usage_response_invalid/)
})

test('限额目录仅接受有效范围与正整数上限，本月已用可以为零', async t => {
  const valid = { id: 'l', scope_kind: 'tenant', scope_id: 'a', monthly_tokens: 10, used_this_month: 0 }
  let response: unknown = { items: [valid] }
  const api = fixture(t).evaluate(source, { '../utils/request': { get: async () => response } })
  assert.equal((await api.listEnterpriseUsageLimits('a'))[0].used_this_month, 0)
  for (const invalid of [{ scope_kind: 'agent' }, { monthly_tokens: 0 }, { used_this_month: -1 }, { scope_id: null }]) {
    response = { items: [{ ...valid, ...invalid }] }
    await assert.rejects(api.listEnterpriseUsageLimits('a'), /usage_response_invalid/)
  }
})

test('范围写入与 null 移除使用真实载荷，拒绝未声明范围或无效数值', async t => {
  const calls: unknown[][] = []
  const api = fixture(t).evaluate(source, { '../utils/request': { put: async (...args: unknown[]) => { calls.push(args) } } })
  await api.saveEnterpriseUsageLimit('a', 'tenant', null, 100)
  await api.saveEnterpriseUsageLimit('a', 'user', 'u', null)
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ['/api/v1/tenants/a/admin/usage/limits', { scope_kind: 'tenant', monthly_tokens: 100 }],
    ['/api/v1/tenants/a/admin/usage/limits', { scope_kind: 'user', scope_id: 'u', monthly_tokens: null }],
  ])
  for (const args of [['a', 'tenant', 'a', 100], ['a', 'user', null, 100], ['a', 'agent', 'x', 100], ['a', 'tenant', null, 0], ['a', 'tenant', null, 1.5]]) await assert.rejects(api.saveEnterpriseUsageLimit(...args), /usage_limit_invalid/)
  assert.equal(calls.length, 2)
})
