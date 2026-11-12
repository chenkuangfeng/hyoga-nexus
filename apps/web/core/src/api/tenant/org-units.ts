import { del, get, patch, post, put } from '@nexus-web/core/utils/request'

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

/** 部门的成员（后端 `UnitMemberView`）。`is_primary` 为主部门；一名成员只有一个主部门。 */
export interface OrgUnitMember {
  user_id: string
  display_name: string | null
  is_primary: boolean
}

/**
 * 新建部门。`parentId` 为空时创建企业根部门（每个企业只能有一个根）。
 * Backend: POST /api/v1/tenants/:id/org-units。
 */
export async function createOrgUnit(
  tenantId: string,
  body: { name: string; parent_id?: string | null },
): Promise<OrgUnitNode> {
  const unit = (await post(`/api/v1/tenants/${tenantId}/org-units`, body)) as unknown as OrgUnitNode
  return unit
}

/**
 * 修改部门：名称、上级（移动）或状态（停用 / 启用）。只发送传入的字段。
 * Backend: PATCH /api/v1/tenants/:id/org-units/:unit_id。
 */
export async function updateOrgUnit(
  tenantId: string,
  unitId: string,
  body: { name?: string; parent_id?: string | null; status?: 'active' | 'disabled' },
): Promise<void> {
  await patch(`/api/v1/tenants/${tenantId}/org-units/${unitId}`, body)
}

/**
 * 删除部门。仍有子部门或成员时后端返回 409。
 * Backend: DELETE /api/v1/tenants/:id/org-units/:unit_id。
 */
export async function deleteOrgUnit(tenantId: string, unitId: string): Promise<void> {
  await del(`/api/v1/tenants/${tenantId}/org-units/${unitId}`)
}

/** 列出部门成员。Backend: GET /api/v1/tenants/:id/org-units/:unit_id/members。 */
export async function listOrgUnitMembers(tenantId: string, unitId: string): Promise<OrgUnitMember[]> {
  const rows = (await get(`/api/v1/tenants/${tenantId}/org-units/${unitId}/members`)) as unknown as OrgUnitMember[]
  return Array.isArray(rows) ? rows : []
}

/**
 * 把成员加入部门（可设为主部门）。Backend: PUT /api/v1/tenants/:id/org-units/:unit_id/members/:user_id。
 */
export async function assignOrgUnitMember(
  tenantId: string,
  unitId: string,
  userId: string,
  isPrimary: boolean,
): Promise<void> {
  await put(`/api/v1/tenants/${tenantId}/org-units/${unitId}/members/${userId}`, { is_primary: isPrimary })
}

/** 把成员移出部门。Backend: DELETE /api/v1/tenants/:id/org-units/:unit_id/members/:user_id。 */
export async function unassignOrgUnitMember(tenantId: string, unitId: string, userId: string): Promise<void> {
  await del(`/api/v1/tenants/${tenantId}/org-units/${unitId}/members/${userId}`)
}
