import { get } from '@/utils/request'

/** 部门树节点（后端 `NodeView`）。停用的节点不能接收新成员。 */
export interface OrgUnitNode {
  id: string
  parent_id: string | null
  name: string
  status: string
  source: string
  member_count: number
}

/**
 * 读取企业的部门树（扁平列表，按 parent_id 组成树）。
 * Backend: GET /api/v1/tenants/:id/org-units/tree（需要 org:manage）。
 */
export async function getOrgUnitTree(tenantId: string): Promise<OrgUnitNode[]> {
  const rows = (await get(`/api/v1/tenants/${tenantId}/org-units/tree`)) as unknown as OrgUnitNode[]
  return Array.isArray(rows) ? rows : []
}

/**
 * 把部门树展开成下拉选项，子部门缩进显示；只保留启用中的部门。
 */
export function flattenOrgUnits(nodes: OrgUnitNode[]): Array<{ label: string; value: string }> {
  const children = new Map<string | null, OrgUnitNode[]>()
  for (const node of nodes) {
    const key = node.parent_id ?? null
    children.set(key, [...(children.get(key) ?? []), node])
  }
  const options: Array<{ label: string; value: string }> = []
  const walk = (parent: string | null, depth: number) => {
    for (const node of children.get(parent) ?? []) {
      if (node.status === 'active') {
        options.push({ label: `${'　'.repeat(depth)}${node.name}`, value: node.id })
      }
      walk(node.id, depth + 1)
    }
  }
  walk(null, 0)
  return options
}
