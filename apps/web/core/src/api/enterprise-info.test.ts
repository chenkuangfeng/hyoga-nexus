import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'

test('企业详情校验拒绝错误类型和不匹配的企业，描述 null 映射为空字符串', t => {
  const api = fixture(t).evaluate(readFileSync(new URL('./enterprise-info.ts', import.meta.url), 'utf8'), { '../utils/request': {} })
  const row = { id: 'a', name: 'Alpha', description: null, role: 'owner', status: 'active', created_at: '2026-11-14' }
  assert.equal(api.enterpriseInfoFromResponse(row, 'a').description, '')
  assert.throws(() => api.enterpriseInfoFromResponse(row, 'b'), /admin_response_invalid/)
  assert.throws(() => api.enterpriseInfoFromResponse({ ...row, name: 42 }, 'a'), /admin_response_invalid/)
})
