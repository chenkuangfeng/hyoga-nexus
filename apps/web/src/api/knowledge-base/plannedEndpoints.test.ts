import assert from 'node:assert/strict'
import { test } from 'node:test'

import { plannedErrorFor } from './plannedEndpoints.ts'

test('unimplemented WeKnora endpoints are planned, Nexus endpoints are not', () => {
  assert.equal(plannedErrorFor('/api/v1/datasource?kb_id=1')?.stage, 'K7')
  assert.equal(plannedErrorFor('/api/v1/datasource')?.feature, '数据源同步')
  assert.equal(plannedErrorFor('/api/v1/initialization/extract/text-relation')?.stage, 'K2')
  assert.equal(plannedErrorFor('http://host:8080/api/v1/system/parser-engines')?.stage, 'K4')
  assert.equal(plannedErrorFor('/api/v1/tenants/t1/knowledge/bases'), null)
  assert.equal(plannedErrorFor('/api/v1/knowledge-bases/x/activity'), null)
  assert.equal(plannedErrorFor(undefined), null)
})
