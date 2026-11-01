import { request, tenantPath } from './chat'
import type { BoundSpace, JoinResult, Org, OrgNode, OrgPerson, SpaceOrganization, UnitMembership, UserOption } from '../types/orgs'

type Row = Record<string, unknown>
function record(value: unknown): Row {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('组织数据格式无效')
  return value as Row
}
function text(value: unknown): string { if (typeof value !== 'string') throw new Error('组织数据格式无效'); return value }
function maybeText(value: unknown): string | null { return value === null || value === undefined ? null : text(value) }
function rows<T>(value: unknown, parse: (row: Row) => T): T[] {
  if (!Array.isArray(value)) throw new Error('组织数据格式无效')
  return value.map(item => parse(record(item)))
}
const json = (method: string, value?: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, ...(value === undefined ? {} : { body: JSON.stringify(value) }) })
const unit = (id: string) => `/org-units/${encodeURIComponent(id)}`
const membership = (row: Row): UnitMembership => ({ unit_id: text(row.unit_id), unit_name: text(row.unit_name), is_primary: row.is_primary === true })
const person = (row: Row): OrgPerson => ({ user_id: text(row.user_id), display_name: maybeText(row.display_name), units: rows(row.units, membership) })
const empty = (_value: unknown): void => undefined
function strings(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every(item => typeof item === 'string')) throw new Error('组织数据格式无效')
  return value as string[]
}

/** Organization management (platform admin) and the organization view of a space. The server decides every check. */
export const orgApi = {
  orgs: (signal?: AbortSignal) => request<Org[]>('/orgs', value => rows(value, row => ({
    id: text(row.id), name: text(row.name), status: text(row.status), created_at: text(row.created_at),
  })), { signal }),
  createOrg: (name: string) => request('/orgs', empty, json('POST', { name })),
  tree: (rootId: string, signal?: AbortSignal) => request<OrgNode[]>(`/orgs/${encodeURIComponent(rootId)}/tree`, value => rows(value, row => ({
    id: text(row.id), parent_id: maybeText(row.parent_id), name: text(row.name), status: text(row.status),
    member_count: typeof row.member_count === 'number' ? row.member_count : 0,
  })), { signal }),
  createUnit: (parentId: string, name: string) => request('/org-units', empty, json('POST', { parent_id: parentId, name })),
  updateUnit: (id: string, body: { name?: string; parent_id?: string; status?: 'active' | 'disabled' }) => request(unit(id), empty, json('PATCH', body)),
  deleteUnit: (id: string) => request(unit(id), empty, json('DELETE')),
  people: (id: string, signal?: AbortSignal) => request<OrgPerson[]>(`${unit(id)}/people`, value => rows(value, person), { signal }),
  assign: (id: string, userId: string, isPrimary: boolean) => request(`${unit(id)}/members/${encodeURIComponent(userId)}`, empty, json('PUT', { is_primary: isPrimary })),
  unassign: (id: string, userId: string) => request(`${unit(id)}/members/${encodeURIComponent(userId)}`, empty, json('DELETE')),
  users: (query: string, signal?: AbortSignal) => request<UserOption[]>(`/users?q=${encodeURIComponent(query)}`, value => rows(value, row => ({
    user_id: text(row.user_id), display_name: maybeText(row.display_name), username: maybeText(row.username),
  })), { signal }),
  bindings: (id: string, signal?: AbortSignal) => request<BoundSpace[]>(`${unit(id)}/bindings`, value => rows(value, row => ({
    tenant_id: text(row.tenant_id), tenant_name: text(row.tenant_name),
  })), { signal }),
  bind: (tenant: string, unitId: string) => request(`${tenantPath(tenant)}/organization-bindings/${encodeURIComponent(unitId)}`, empty, json('PUT')),
  unbind: (tenant: string, unitId: string) => request(`${tenantPath(tenant)}/organization-bindings/${encodeURIComponent(unitId)}`, empty, json('DELETE')),
  spaceOrganization: (tenant: string, signal?: AbortSignal) => request<SpaceOrganization>(`${tenantPath(tenant)}/organization`, value => {
    const row = record(value)
    return {
      bindings: rows(row.bindings, item => ({
        unit_id: text(item.unit_id), unit_name: text(item.unit_name), organization_name: text(item.organization_name), status: text(item.status),
        nodes: rows(item.nodes, node => ({ id: text(node.id), parent_id: maybeText(node.parent_id), name: text(node.name), status: text(node.status) })),
      })),
      people: rows(row.people, person),
    }
  }, { signal }),
  joinFromOrganization: (tenant: string, userIds: string[], role: 'admin' | 'member') => request<JoinResult>(`${tenantPath(tenant)}/members/from-organization`, value => {
    const row = record(value)
    return { added: strings(row.added), skipped: strings(row.skipped) }
  }, json('POST', { user_ids: userIds, role })),
}
