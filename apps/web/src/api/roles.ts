import { request, tenantPath } from './chat'
import { i18n } from '../i18n'
import { AGENT_PERMISSIONS, type AgentGrantRow, type AgentPermission, type PermissionCatalog, type Permissions,
  type RoleAssignment, type TenantMember, type TenantRole } from '../types/roles'

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(i18n.global.t('errors.dataInvalid'))
  return value as Record<string, unknown>
}
function text(value: unknown): string { if (typeof value !== 'string') throw new Error(i18n.global.t('errors.dataInvalid')); return value }
function strings(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every(item => typeof item === 'string')) throw new Error(i18n.global.t('errors.dataInvalid'))
  return value as string[]
}
function rows<T>(value: unknown, parse: (row: Record<string, unknown>) => T): T[] {
  if (!Array.isArray(value)) throw new Error(i18n.global.t('errors.dataInvalid'))
  return value.map(item => parse(record(item)))
}
function agentPermission(value: unknown): AgentPermission {
  const permission = text(value)
  if (!(AGENT_PERMISSIONS as readonly string[]).includes(permission)) throw new Error(i18n.global.t('errors.dataInvalid'))
  return permission as AgentPermission
}
const role = (row: Record<string, unknown>): TenantRole => ({ id: text(row.id), tenant_id: text(row.tenant_id), name: text(row.name), menus: strings(row.menus), apis: strings(row.apis) })
const json = (method: string, value?: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, ...(value === undefined ? {} : { body: JSON.stringify(value) }) })
const base = (tenant: string) => `${tenantPath(tenant)}`
/** Accepts 204 responses (null body); the server signals success by status alone. */
const empty = (_value: unknown): void => undefined

/** Role management requests. Server checks are authoritative; hiding controls is UX only. */
export const roleApi = {
  catalog: (tenant: string, signal?: AbortSignal) => request<PermissionCatalog>(`${base(tenant)}/permission-catalog`, value => {
    const row = record(value); return { menus: strings(row.menus), apis: strings(row.apis) }
  }, { signal }),
  myPermissions: (tenant: string, signal?: AbortSignal) => request<Permissions>(`${base(tenant)}/me/permissions`, value => {
    const row = record(value); return { menus: strings(row.menus), apis: strings(row.apis) }
  }, { signal }),
  roles: (tenant: string, signal?: AbortSignal) => request<TenantRole[]>(`${base(tenant)}/roles`, value => rows(value, role), { signal }),
  createRole: (tenant: string, name: string, menus: string[], apis: string[]) => request<TenantRole>(`${base(tenant)}/roles`, value => role(record(value)), json('POST', { name, menus, apis })),
  updateRole: (tenant: string, id: string, menus: string[], apis: string[]) => request<TenantRole>(`${base(tenant)}/roles/${encodeURIComponent(id)}`, value => role(record(value)), json('PUT', { menus, apis })),
  members: (tenant: string, signal?: AbortSignal) => request<TenantMember[]>(`${base(tenant)}/members`, value => rows(value, row => ({
    tenant_id: text(row.tenant_id), user_id: text(row.user_id), role: text(row.role) as TenantMember['role'], status: text(row.status),
  })), { signal }),
  assignments: (tenant: string, signal?: AbortSignal) => request<RoleAssignment[]>(`${base(tenant)}/role-assignments`, value => rows(value, row => ({
    user_id: text(row.user_id), role_id: text(row.role_id),
  })), { signal }),
  assign: (tenant: string, member: string, roleId: string) => request(`${base(tenant)}/members/${encodeURIComponent(member)}/roles/${encodeURIComponent(roleId)}`, empty, json('PUT')),
  unassign: (tenant: string, member: string, roleId: string) => request(`${base(tenant)}/members/${encodeURIComponent(member)}/roles/${encodeURIComponent(roleId)}`, empty, json('DELETE')),
  agentGrants: (tenant: string, signal?: AbortSignal) => request<AgentGrantRow[]>(`${base(tenant)}/agent-grants`, value => rows(value, row => ({
    role_id: text(row.role_id), agent_id: text(row.agent_id), permission: agentPermission(row.permission),
  })), { signal }),
  createAccount: (tenant: string, username: string, display_name: string, password: string, role: 'admin' | 'member') => request(`${base(tenant)}/accounts`, empty, json('POST', { username, display_name, password, role })),
  setAgentGrants: (tenant: string, roleId: string, agentId: string, permissions: AgentPermission[]) => request(`${base(tenant)}/roles/${encodeURIComponent(roleId)}/agents/${encodeURIComponent(agentId)}`, empty, json('PUT', { permissions })),
}
