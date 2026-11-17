/** 企业 Token 用量报表与月度上限；金额不在现有服务端契约中。 */
import { get, put } from '../utils/request'

export type UsageGroup = 'day' | 'user' | 'org_unit'
export interface EnterpriseUsageRow { key: string; runs: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; cache_creation_tokens: number }
export interface EnterpriseUsageLimit { id: string; scope_kind: 'tenant' | 'org_unit' | 'user'; scope_id: string; monthly_tokens: number; used_this_month: number }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('usage_response_invalid'); return value as Record<string, unknown> }
function text(value: unknown): string { if (typeof value !== 'string') throw new Error('usage_response_invalid'); return value }
function count(value: unknown): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('usage_response_invalid'); return value }
function base(tenant: string) { return `/api/v1/tenants/${encodeURIComponent(tenant)}/admin/usage` }
function rowsFromResponse(value: unknown): EnterpriseUsageRow[] {
  const items = object(value).items
  if (!Array.isArray(items)) throw new Error('usage_response_invalid')
  return items.map(item => { const row = object(item); return { key: text(row.key), runs: count(row.runs), input_tokens: count(row.input_tokens), output_tokens: count(row.output_tokens), cache_read_tokens: count(row.cache_read_tokens), cache_creation_tokens: count(row.cache_creation_tokens) } })
}
function limitsFromResponse(value: unknown): EnterpriseUsageLimit[] {
  const items = object(value).items
  if (!Array.isArray(items)) throw new Error('usage_response_invalid')
  return items.map(item => { const row = object(item); if (!['tenant', 'org_unit', 'user'].includes(String(row.scope_kind)) || count(row.monthly_tokens) < 1) throw new Error('usage_response_invalid'); return { id: text(row.id), scope_kind: row.scope_kind as EnterpriseUsageLimit['scope_kind'], scope_id: text(row.scope_id), monthly_tokens: count(row.monthly_tokens), used_this_month: count(row.used_this_month) } })
}
/** 日期为闭区间自然日；接口返回已归一化的 Run 计数和 Token 数。 */
export async function getEnterpriseUsage(tenant: string, groupBy: UsageGroup, start: string, end: string): Promise<EnterpriseUsageRow[]> {
  const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
  if (!validDate(start) || !validDate(end) || start > end) throw new Error('usage_dates_invalid')
  return rowsFromResponse(await get(base(tenant), { params: { group_by: groupBy, start, end } }))
}
export async function listEnterpriseUsageLimits(tenant: string): Promise<EnterpriseUsageLimit[]> { return limitsFromResponse(await get(`${base(tenant)}/limits`)) }
/** null 移除该范围限额；tenant 范围不提交 scope_id。 */
export async function saveEnterpriseUsageLimit(tenant: string, scopeKind: EnterpriseUsageLimit['scope_kind'], scopeId: string | null, monthlyTokens: number | null): Promise<void> {
  if (!['tenant', 'org_unit', 'user'].includes(scopeKind) || (scopeKind === 'tenant' && scopeId !== null) || (scopeKind !== 'tenant' && !scopeId)
      || (monthlyTokens !== null && (!Number.isSafeInteger(monthlyTokens) || monthlyTokens < 1))) throw new Error('usage_limit_invalid')
  await put(`${base(tenant)}/limits`, { scope_kind: scopeKind, ...(scopeId ? { scope_id: scopeId } : {}), monthly_tokens: monthlyTokens })
}
