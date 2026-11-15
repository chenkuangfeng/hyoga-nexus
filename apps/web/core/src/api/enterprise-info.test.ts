import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'

test('企业详情校验拒绝错误类型和不匹配的企业，描述 null 映射为空字符串', t => {
  const api = fixture(t).evaluate(readFileSync(new URL('./enterprise-info.ts', import.meta.url), 'utf8'), { '../utils/request': {} })
  const row = { id: 'a', code: 'alpha_01', name: 'Alpha', description: null, role: 'owner', status: 'active', created_at: '2026-11-14' }
  assert.equal(api.enterpriseInfoFromResponse(row, 'a').description, '')
  assert.throws(() => api.enterpriseInfoFromResponse(row, 'b'), /admin_response_invalid/)
  assert.throws(() => api.enterpriseInfoFromResponse({ ...row, name: 42 }, 'a'), /admin_response_invalid/)
})

 test('企业编码保留真实值及 null，缺失和非字符串字段显式失败', t => {
  const api = fixture(t).evaluate(readFileSync(new URL('./enterprise-info.ts', import.meta.url), 'utf8'), { '../utils/request': {} })
  const row = { id: 'a', code: 'real-code', name: 'Alpha', description: '', role: 'owner', status: 'active', created_at: 'date' }
  assert.equal(api.enterpriseInfoFromResponse(row, 'a').code, 'real-code')
  assert.equal(api.enterpriseInfoFromResponse({ ...row, code: null }, 'a').code, null)
  for (const code of [undefined, 42, {}, []]) assert.throws(() => api.enterpriseInfoFromResponse({ ...row, code }, 'a'), /admin_response_invalid/)
})
