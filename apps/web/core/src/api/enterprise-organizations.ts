/** 企业组织与成员归属客户端。只消费 Nexus 真实契约，所有路径都限定到当前企业。 */
import { del, get, patch, post, put } from '../utils/request'
export type OrganizationStatus = 'active' | 'disabled'
export type OrganizationSource = 'manual' | 'wecom'
export interface OrganizationNode { id: string; parent_id: string | null; name: string; status: OrganizationStatus; source: OrganizationSource; member_count: number }
export interface OrganizationUnit extends Omit<OrganizationNode, 'member_count'> { tenant_id: string; root_id: string }
export interface OrganizationMember { user_id: string; display_name: string | null; is_primary: boolean }
export interface OrganizationLink { unit_id: string; user_id: string; is_primary: boolean }
export interface OrganizationEdit { name?: string; parent_id?: string; status?: OrganizationStatus }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('organization_response_invalid'); return value as Record<string, unknown> }
function text(value: unknown): string { if (typeof value !== 'string') throw new Error('organization_response_invalid'); return value }
function id(value: unknown): string { const result = text(value); if (!result.trim()) throw new Error('organization_response_invalid'); return result }
function boolean(value: unknown): boolean { if (typeof value !== 'boolean') throw new Error('organization_response_invalid'); return value }
function fields(value: unknown): Omit<OrganizationNode, 'member_count'> {
  const row = object(value), name = text(row.name)
  if (!name.trim() || !['active', 'disabled'].includes(text(row.status)) || !['manual', 'wecom'].includes(text(row.source))) throw new Error('organization_response_invalid')
  return { id: id(row.id), parent_id: row.parent_id === null ? null : id(row.parent_id), name, status: row.status as OrganizationStatus, source: row.source as OrganizationSource }
}
function tenantPath(tenant: string, admin = true): string { return `/api/v1/tenants/${encodeURIComponent(tenant)}${admin ? '/admin' : ''}/org-units` }
function unitPath(tenant: string, unit: string): string { return `${tenantPath(tenant)}/${encodeURIComponent(unit)}` }
function detail(value: unknown, tenant: string): OrganizationUnit {
  const row = object(value), base = fields(row), root = id(row.root_id)
  if (id(row.tenant_id) !== tenant || (base.parent_id === null ? base.id !== root : base.id === root) || base.parent_id === base.id) throw new Error('organization_response_invalid')
  return { ...base, tenant_id: tenant, root_id: root }
}
/** 校验单根、唯一节点、完整父引用和无环连通结构，避免错误树导致隐藏节点或错误移动选项。 */
export function organizationTreeFromResponse(value: unknown): OrganizationNode[] {
  if (!Array.isArray(value)) throw new Error('organization_response_invalid')
  const nodes = value.map(item => {
    const row = object(item), base = fields(row), count = row.member_count
    if (typeof count !== 'number' || !Number.isSafeInteger(count) || count < 0) throw new Error('organization_response_invalid')
    return { ...base, member_count: count }
  })
  if (!nodes.length) return nodes
  const ids = new Set(nodes.map(row => row.id)), roots = nodes.filter(row => row.parent_id === null)
  if (ids.size !== nodes.length || roots.length !== 1 || nodes.some(row => row.parent_id !== null && !ids.has(row.parent_id))) throw new Error('organization_response_invalid')
  const children = new Map<string, string[]>()
  for (const row of nodes) if (row.parent_id !== null) { const bucket = children.get(row.parent_id); if (bucket) bucket.push(row.id); else children.set(row.parent_id, [row.id]) }
  const pending = [roots[0].id], seen = new Set<string>()
  while (pending.length) { const next = pending.pop()!; if (seen.has(next)) throw new Error('organization_response_invalid'); seen.add(next); for (const child of children.get(next) || []) pending.push(child) }
  if (seen.size !== nodes.length) throw new Error('organization_response_invalid')
  return nodes
}
/** 读取全企业组织树；需要 org:manage。空数组表示尚未创建根部门。 */
export async function listOrganizationUnits(tenant: string, admin = true): Promise<OrganizationNode[]> { return organizationTreeFromResponse(await get(`${tenantPath(tenant, admin)}/tree`)) }
/** 不传 parent_id 创建唯一根；传入时创建手工子部门。校验返回企业与父节点。 */
export async function createOrganizationUnit(tenant: string, input: { name: string; parent_id?: string }): Promise<OrganizationUnit> {
  const row = detail(await post(tenantPath(tenant), input), tenant)
  if (row.parent_id !== (input.parent_id ?? null)) throw new Error('organization_response_invalid')
  return row
}
/** 更新名称、父节点或状态；根节点和环路规则仍由后端事务复核。 */
export async function updateOrganizationUnit(tenant: string, unit: string, input: OrganizationEdit): Promise<OrganizationUnit> {
  const row = detail(await patch(unitPath(tenant, unit), input), tenant)
  if (row.id !== unit || (input.parent_id !== undefined && row.parent_id !== input.parent_id)) throw new Error('organization_response_invalid')
  return row
}
/** 删除非根且无子节点/成员关联的部门；历史成员关联也可能使后端拒绝，不能只信 member_count。 */
export async function deleteOrganizationUnit(tenant: string, unit: string): Promise<void> { await del(unitPath(tenant, unit)) }
/** 读取当前节点直接关联的活跃成员，保留服务端主部门标记。 */
export async function listOrganizationMembers(tenant: string, unit: string): Promise<OrganizationMember[]> {
  const data: unknown = await get(`${unitPath(tenant, unit)}/members`)
  if (!Array.isArray(data)) throw new Error('organization_response_invalid')
  const rows = data.map(value => { const row = object(value); return { user_id: id(row.user_id), display_name: row.display_name == null ? null : text(row.display_name), is_primary: boolean(row.is_primary) } })
  if (new Set(rows.map(row => row.user_id)).size !== rows.length) throw new Error('organization_response_invalid')
  return rows
}
/** 分配成员或设置主部门；第一次分配可能由服务器自动设为主部门，不假定回执标记等于输入。 */
export async function assignOrganizationMember(tenant: string, unit: string, user: string, primary: boolean): Promise<OrganizationLink> {
  const row = object(await put(`${unitPath(tenant, unit)}/members/${encodeURIComponent(user)}`, { is_primary: primary }))
  if (id(row.unit_id) !== unit || id(row.user_id) !== user) throw new Error('organization_response_invalid')
  return { unit_id: unit, user_id: user, is_primary: boolean(row.is_primary) }
}
/** 只移除部门关联，不移出企业；主部门仍有其他关联时，后端要求先改设主部门。 */
export async function removeOrganizationMember(tenant: string, unit: string, user: string): Promise<void> { await del(`${unitPath(tenant, unit)}/members/${encodeURIComponent(user)}`) }
