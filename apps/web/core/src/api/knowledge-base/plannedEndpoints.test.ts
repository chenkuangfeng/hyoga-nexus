import assert from 'node:assert/strict'
import { test } from 'node:test'

import { plannedErrorFor } from './plannedEndpoints.ts'

test('unimplemented WeKnora endpoints are planned, Nexus endpoints are not', () => {
  assert.equal(plannedErrorFor('/api/v1/datasource?kb_id=1')?.stage, 'K7')
  assert.equal(plannedErrorFor('/api/v1/datasource')?.feature, '数据源同步')
  assert.equal(plannedErrorFor('/api/v1/initialization/extract/text-relation')?.feature, '知识图谱抽取预览（图谱在库设置中构建）')
  assert.equal(plannedErrorFor('http://host:8080/api/v1/system/parser-engines/check')?.feature, '外部解析服务探测')
  assert.equal(plannedErrorFor('/api/v1/system/docreader/reconnect')?.stage, null)
  assert.equal(plannedErrorFor('/api/v1/organizations/o1/shared-knowledge-bases')?.feature, '共享空间内知识库浏览')
  // Knowledge base sharing now goes to Nexus, so it is no longer short-circuited.
  assert.equal(plannedErrorFor('/api/v1/knowledge-bases/k1/shares'), null)
  assert.equal(plannedErrorFor('/api/v1/tenants/t1/knowledge/bases'), null)
  assert.equal(plannedErrorFor('/api/v1/knowledge-bases/x/activity'), null)
  assert.equal(plannedErrorFor(undefined), null)
})
