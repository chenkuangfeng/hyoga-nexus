/** 企业审计只消费现有元数据列表和 UTC 日期范围 JSONL 导出，不冒充正文或全量分页。 */
import { get, getDown } from '../utils/request'
export interface EnterpriseAuditRecord { id: string; actor_user_id: string | null; action: string; target_type: string; target_id: string; result: string; metadata: Record<string, unknown> | null; created_at: string }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('audit_response_invalid'); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('audit_response_invalid'); return value }
/** 未知动作/结果保留原值；不把错误响应当作成功空列表。 */
export function auditRecordsFromResponse(value: unknown): EnterpriseAuditRecord[] {
  if (!Array.isArray(value)) throw new Error('audit_response_invalid')
  return value.map(value => {
    const row = object(value)
    return { id: string(row.id), actor_user_id: row.actor_user_id === null ? null : string(row.actor_user_id), action: string(row.action), target_type: string(row.target_type), target_id: string(row.target_id), result: string(row.result), metadata: row.metadata === null ? null : object(row.metadata), created_at: string(row.created_at) }
  })
}
const base = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}`
export async function listEnterpriseAudit(tenant: string, limit: number): Promise<EnterpriseAuditRecord[]> {
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new Error('audit_limit_invalid')
  return auditRecordsFromResponse(await get(`${base(tenant)}/admin/audit`, { params: { limit } }))
}
/** 严格自然日校验，不允许 Date 自动把无效日期归一化；与服务端日期差上限一致。 */
export function validAuditExportRange(start: string, end: string): boolean {
  const day = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number(value.slice(0, 4)) >= 1 && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
  if (!day(start) || !day(end)) return false
  const difference = (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000
  return difference >= 0 && difference <= 366
}
export async function exportEnterpriseAudit(tenant: string, start: string, end: string): Promise<Blob> {
  if (!validAuditExportRange(start, end)) throw new Error('audit_dates_invalid')
  const blob = await getDown(`${base(tenant)}/admin/audit/export?${new URLSearchParams({ start, end })}`)
  if (!blob || typeof blob.size !== 'number' || !blob.type?.includes('application/x-ndjson')) throw new Error('audit_response_invalid')
  return blob
}
