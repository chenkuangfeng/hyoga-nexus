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
export async function listEnterpriseRoles(tenant: string): Promise<EnterpriseRole[]> { return array(await get(`${base(tenant)}/roles`)).map(row => roleFromResponse(row, tenant)) }
export async function getRoleCatalog(tenant: string): Promise<PermissionSet> { return permissionsFromResponse(await get(`${base(tenant)}/permission-catalog`)) }
export async function getRoleActorPermissions(tenant: string): Promise<PermissionSet> { return permissionsFromResponse(await get(`${base(tenant)}/me/permissions`)) }
export async function createEnterpriseRole(tenant: string, input: PermissionSet & { name: string }): Promise<EnterpriseRole> { return roleFromResponse(await post(`${base(tenant)}/roles`, input), tenant) }
/** 现有 PUT 整体替换权限，不支持改名或修改内置角色。 */
export async function updateEnterpriseRole(tenant: string, id: string, input: PermissionSet): Promise<EnterpriseRole> { return roleFromResponse(await put(`${base(tenant)}/roles/${encodeURIComponent(id)}`, input), tenant) }
export async function listRoleAssignments(tenant: string): Promise<RoleAssignment[]> {
  return array(await get(`${base(tenant)}/role-assignments`)).map(value => { const row = object(value); return { user_id: string(row.user_id), role_id: string(row.role_id) } })
}
/** 分配不替换成员基础角色；撤销仅移除这一项自定义角色分配。 */
export async function setMemberRoleAssignment(tenant: string, user: string, role: string, assigned: boolean): Promise<void> {
  const url = `${base(tenant)}/members/${encodeURIComponent(user)}/roles/${encodeURIComponent(role)}`
  if (assigned) await put(url, {})
  else await del(url)
}
