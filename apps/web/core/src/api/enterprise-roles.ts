/** 企业角色管理客户端；运行时校验当前企业作用域，沿用既有授权契约。 */
import { get, post, put, del } from '../utils/request'
export interface PermissionSet { menus: string[]; apis: string[] }
export interface EnterpriseRole extends PermissionSet { id: string; tenant_id: string; name: string; builtin: boolean }
export interface RoleAssignment { user_id: string; role_id: string }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('roles_response_invalid')
  return value as Record<string, unknown>
}
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('roles_response_invalid'); return value }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error('roles_response_invalid'); return value }
/** 权限目录与有效授权必须显式提供菜单和 API 两组，缺失不视为空授权。 */
export function permissionsFromResponse(value: unknown): PermissionSet {
  const row = object(value)
  return { menus: array(row.menus).map(string), apis: array(row.apis).map(string) }
}
/** 拒绝跨企业角色及非布尔的 builtin 标记。 */
export function roleFromResponse(value: unknown, tenantId: string): EnterpriseRole {
  const row = object(value)
  if (row.tenant_id !== tenantId || typeof row.builtin !== 'boolean') throw new Error('roles_response_invalid')
  return { id: string(row.id), tenant_id: tenantId, name: string(row.name), builtin: row.builtin, ...permissionsFromResponse(row) }
}
const base = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}`
const adminBase = (tenant: string) => `${base(tenant)}/admin`
export async function listEnterpriseRoles(tenant: string): Promise<EnterpriseRole[]> { return array(await get(`${adminBase(tenant)}/roles`)).map(row => roleFromResponse(row, tenant)) }
export async function getRoleCatalog(tenant: string): Promise<PermissionSet> { return permissionsFromResponse(await get(`${adminBase(tenant)}/permission-catalog`)) }
export async function getRoleActorPermissions(tenant: string): Promise<PermissionSet> { return permissionsFromResponse(await get(`${base(tenant)}/me/permissions`)) }
export async function createEnterpriseRole(tenant: string, input: PermissionSet & { name: string }): Promise<EnterpriseRole> { return roleFromResponse(await post(`${adminBase(tenant)}/roles`, input), tenant) }
/** 现有 PUT 整体替换权限，不支持改名或修改内置角色。 */
export async function updateEnterpriseRole(tenant: string, id: string, input: PermissionSet): Promise<EnterpriseRole> { return roleFromResponse(await put(`${adminBase(tenant)}/roles/${encodeURIComponent(id)}`, input), tenant) }
export async function listRoleAssignments(tenant: string): Promise<RoleAssignment[]> {
  return array(await get(`${adminBase(tenant)}/role-assignments`)).map(value => { const row = object(value); return { user_id: string(row.user_id), role_id: string(row.role_id) } })
}
/** 分配不替换成员基础角色；撤销仅移除这一项自定义角色分配。 */
export async function setMemberRoleAssignment(tenant: string, user: string, role: string, assigned: boolean): Promise<void> {
  const url = `${adminBase(tenant)}/members/${encodeURIComponent(user)}/roles/${encodeURIComponent(role)}`
  if (assigned) await put(url, {})
  else await del(url)
}

export interface DepartmentAssignmentResult { assigned: string[]; skipped: string[] }
/** 仅分配所选启用部门的直接活跃非 owner 成员；已有分配跳过，返回实际结果。 */
export async function assignDepartmentRole(tenant: string, unit: string, role: string): Promise<DepartmentAssignmentResult> {
  const row = object(await post(`${adminBase(tenant)}/org-units/${encodeURIComponent(unit)}/role-assignments`, { role_id: role }))
  const assigned = array(row.assigned).map(string), skipped = array(row.skipped).map(string)
  if (new Set([...assigned, ...skipped]).size !== assigned.length + skipped.length) throw new Error('roles_response_invalid')
  return { assigned, skipped }
}

export type AgentUsePermission = 'view' | 'run'
export interface RoleAgentGrant { role_id: string; agent_id: string; permission: AgentUsePermission }
export interface RoleAgentChoice { id: string; name: string }
function usePermissions(value: unknown): AgentUsePermission[] {
  return array(value).map(value => { if (value !== 'view' && value !== 'run') throw new Error('roles_response_invalid'); return value })
}
/** 当前可见列表受模型/发布状态过滤，只返回企业资源；不宣称是企业完整资源目录。 */
export async function listRoleAgentChoices(tenant: string): Promise<RoleAgentChoice[]> {
  const rows = array(await get(`${adminBase(tenant)}/agents`)).map(value => {
    const row = object(value)
    if (row.tenant_id !== tenant || !['personal', 'enterprise'].includes(string(row.ownership))) throw new Error('roles_response_invalid')
    return { id: string(row.id), name: string(row.name), ownership: row.ownership }
  })
  return rows.filter(row => row.ownership === 'enterprise').map(({ id, name }) => ({ id, name }))
}
export async function listRoleAgentGrants(tenant: string): Promise<RoleAgentGrant[]> {
  return array(await get(`${adminBase(tenant)}/agent-grants`)).map(value => { const row = object(value); return { role_id: string(row.role_id), agent_id: string(row.agent_id), permission: usePermissions([row.permission])[0] } })
}
/** 整体替换一个角色的智能体使用授权；空数组撤销，最终权限与知识库范围由服务端复核。 */
export async function setRoleAgentGrants(tenant: string, role: string, agent: string, permissions: AgentUsePermission[]): Promise<void> {
  const input = usePermissions(permissions)
  const row = object(await put(`${adminBase(tenant)}/roles/${encodeURIComponent(role)}/agents/${encodeURIComponent(agent)}`, { permissions: input }))
  if (row.role_id !== role || row.agent_id !== agent) throw new Error('roles_response_invalid')
  const result = usePermissions(row.permissions)
  if (new Set(result).size !== result.length || result.length !== new Set(input).size || result.some(p => !input.includes(p))) throw new Error('roles_response_invalid')
}
