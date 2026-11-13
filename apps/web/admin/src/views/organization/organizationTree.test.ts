import assert from 'node:assert/strict'
import test from 'node:test'
import { organizationRows, organizationSubtree } from './organizationTree'
import type { OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'
const node = (id: string, parent_id: string | null, name = id): OrganizationNode => ({ id, parent_id, name, status: 'active', source: 'manual', member_count: 0 })
test('组织行按层级展开，路径能区分同名节点，移动排除完整子树', () => {
  const nodes = [node('r', null, '公司'), node('a', 'r', '子公司A'), node('b', 'r', '子公司B'), node('x', 'a', '研发'), node('y', 'b', '研发')]
  const rows = organizationRows(nodes)
  assert.deepEqual(rows.map(row => row.node.id), ['r', 'a', 'x', 'b', 'y'])
  assert.equal(rows[2].path, '公司 / 子公司A / 研发'); assert.equal(rows[4].path, '公司 / 子公司B / 研发')
  assert.deepEqual([...organizationSubtree(nodes, 'a')], ['a', 'x'])
})
test('子树遍历防御循环数据，不会无限执行', () => {
  assert.deepEqual([...organizationSubtree([node('a', 'b'), node('b', 'a')], 'a')], ['a', 'b'])
})
