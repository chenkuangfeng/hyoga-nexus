import { request } from './chat'
import type { Tenant } from '../types/chat'

/** A session as seen by a platform administrator across spaces. Memory is never part of this list. */
export interface AdminSession {
  id: string
  tenant_id: string
  owner_user_id: string
  title: string
  org_unit_id: string | null
  updated_at: string
}

type Row = Record<string, unknown>
function record(value: unknown): Row {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('会话数据格式无效')
  return value as Row
}
function text(value: unknown): string { if (typeof value !== 'string') throw new Error('会话数据格式无效'); return value }
function rows<T>(value: unknown, parse: (row: Row) => T): T[] {
  if (!Array.isArray(value)) throw new Error('会话数据格式无效')
  return value.map(item => parse(record(item)))
}

/** Platform-administrator endpoints. Other users receive 403 from the server. */
export const adminSessionApi = {
  tenants: (signal?: AbortSignal) => request<Tenant[]>('/admin/tenants', value => rows(value, row => ({
    id: text(row.id), name: text(row.name), via_organization: false,
  })), { signal }),
  sessions: (filter: { tenantId?: string; orgUnitId?: string }, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    if (filter.tenantId) query.set('tenant_id', filter.tenantId)
    if (filter.orgUnitId) query.set('org_unit_id', filter.orgUnitId)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request<AdminSession[]>(`/admin/sessions${suffix}`, value => rows(value, row => ({
      id: text(row.id), tenant_id: text(row.tenant_id), owner_user_id: text(row.owner_user_id), title: typeof row.title === 'string' ? row.title : '',
      org_unit_id: row.org_unit_id === null || row.org_unit_id === undefined ? null : text(row.org_unit_id),
      updated_at: text(row.updated_at),
    })), { signal })
  },
}
