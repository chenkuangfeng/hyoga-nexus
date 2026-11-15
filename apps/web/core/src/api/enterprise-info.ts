/** 企业信息客户端：保留现有 HTTP 契约，校验当前企业身份，不把 ID 当企业编码。 */
import { get, patch, del } from '../utils/request'

export interface EnterpriseInfo { id: string; name: string; description: string; role: string; status: string; created_at: string }
/** 仅接受完整企业详情，避免错误响应被当作成功空数据。 */
export function enterpriseInfoFromResponse(value: unknown, tenantId: string): EnterpriseInfo {
  if (!value || typeof value !== 'object') throw new Error('admin_response_invalid')
  const row = value as Record<string, unknown>
  for (const key of ['id', 'name', 'role', 'status', 'created_at']) {
    if (typeof row[key] !== 'string') throw new Error('admin_response_invalid')
  }
  if (row.id !== tenantId || (row.description !== null && typeof row.description !== 'string')) throw new Error('admin_response_invalid')
  return { id: row.id as string, name: row.name as string, role: row.role as string, status: row.status as string, created_at: row.created_at as string, description: row.description as string | null ?? '' }
}
/** 当前企业由已认证请求层的 X-Tenant-ID 指定；响应必须与调用时作用域一致。 */
export async function getEnterpriseInfo(tenantId: string, admin = false): Promise<EnterpriseInfo> {
  const path = admin ? `/api/v1/tenants/${encodeURIComponent(tenantId)}/admin` : '/api/v1/tenants/current'
  return enterpriseInfoFromResponse(await get(path), tenantId)
}
/** 只提交变化字段；description 空字符串明确清空描述。服务端复核管理权限。 */
export async function updateEnterpriseInfo(tenantId: string, changes: { name?: string; description?: string }, admin = false): Promise<EnterpriseInfo> {
  const path = admin ? `/api/v1/tenants/${encodeURIComponent(tenantId)}/admin` : '/api/v1/tenants/current'
  return enterpriseInfoFromResponse(await patch(path, changes), tenantId)
}
/** 删除由服务端归档，仅 owner 可操作；关联共享空间冲突由服务端返回。 */
export async function archiveEnterprise(tenantId: string): Promise<void> {
  await del(`/api/v1/tenants/${encodeURIComponent(tenantId)}/admin`)
}
