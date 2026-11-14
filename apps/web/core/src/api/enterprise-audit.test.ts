import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fixture } from '../test-utils/vueFixture'
function api(t: Parameters<typeof fixture>[0]) { return fixture(t).evaluate(readFileSync(new URL('./enterprise-audit.ts', import.meta.url), 'utf8'), { '../utils/request': {} }) }
test('日期范围按 UTC 自然日校验，拒绝归一化日期、反向范围和超出 366 天', t => {
  const s = api(t)
  assert.equal(s.validAuditExportRange('2024-02-29', '2025-03-01'), true)
  for (const [start, end] of [['2025-02-29','2025-03-01'],['0000-01-01','0000-01-01'],['2026-03-02','2026-03-01'],['2024-01-01','2025-01-02'],['bad','2025-01-01']]) assert.equal(s.validAuditExportRange(start,end),false)
})
test('审计响应保留未知动作/结果，拒绝错误结构与错误元数据', t => {
  const s = api(t), row = { id:'a',actor_user_id:null,action:'future.action',target_type:'agent',target_id:'id',result:'future',metadata:{label:'<script>text</script>'},created_at:'2026-11-14' }
  assert.equal(s.auditRecordsFromResponse([row])[0].result,'future')
  assert.throws(() => s.auditRecordsFromResponse({ error:'failed' }), /audit_response_invalid/)
  assert.throws(() => s.auditRecordsFromResponse([{...row,metadata:'bad'}]), /audit_response_invalid/)
})
