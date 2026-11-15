/** 企业策略管理客户端。请求始终带企业路径，字段在消费前校验，权限由服务端复核。 */
import { get, patch } from '../utils/request'

export interface EnterprisePolicy {
  self_build_agents: 'all' | 'org_units' | 'none'
  self_build_org_unit_ids: string[]
  personal_models: boolean
  external_sharing: boolean
  personal_wecom_channels: 'review' | 'open' | 'disabled'
  personal_external_channels: boolean
  retention_days: number | null
}
export interface DepartmentChoice { id: string; name: string; status: string; parent_id: string | null }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('admin_response_invalid')
  return value as Record<string, unknown>
}
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('admin_response_invalid'); return value }
function boolean(value: unknown): boolean { if (typeof value !== 'boolean') throw new Error('admin_response_invalid'); return value }
function strings(value: unknown): string[] { if (!Array.isArray(value)) throw new Error('admin_response_invalid'); return value.map(string) }
function tenantPath(tenantId: string): string { return `/api/v1/tenants/${encodeURIComponent(tenantId)}` }

/** 校验策略的枚举、布尔值和保留天数；错误响应抛出 admin_response_invalid。 */
export function policyFromResponse(value: unknown): EnterprisePolicy {
  const row = object(value), mode = string(row.self_build_agents), channel = string(row.personal_wecom_channels)
  if (!['all', 'org_units', 'none'].includes(mode) || !['review', 'open', 'disabled'].includes(channel)) throw new Error('admin_response_invalid')
  const days = row.retention_days
  if (days !== null && (typeof days !== 'number' || !Number.isInteger(days) || days < 1 || days > 3650)) throw new Error('admin_response_invalid')
  return { self_build_agents: mode as EnterprisePolicy['self_build_agents'], self_build_org_unit_ids: strings(row.self_build_org_unit_ids),
    personal_models: boolean(row.personal_models), external_sharing: boolean(row.external_sharing), personal_wecom_channels: channel as EnterprisePolicy['personal_wecom_channels'],
    personal_external_channels: boolean(row.personal_external_channels), retention_days: days as number | null }
}
/** 所有有效成员均可读取；返回当前企业完整策略。 */
export async function getEnterprisePolicy(tenantId: string): Promise<EnterprisePolicy> {
  return policyFromResponse(await get(`${tenantPath(tenantId)}/admin/policy`))
}
/** 只提交变化字段；显式 null 表示不自动清理，不得用省略字段代替。要求 policy:manage。 */
export async function updateEnterprisePolicy(tenantId: string, changes: Partial<EnterprisePolicy>): Promise<EnterprisePolicy> {
  return policyFromResponse(await patch(`${tenantPath(tenantId)}/admin/policy`, changes))
}
/** 按名称展示组织节点，提交稳定 ID。要求 org:manage；失败时不得手工输入 ID 绕过。 */
export async function listPolicyDepartments(tenantId: string): Promise<DepartmentChoice[]> {
  const data: unknown = await get(`${tenantPath(tenantId)}/admin/org-units/tree`)
  if (!Array.isArray(data)) throw new Error('admin_response_invalid')
  return data.map(value => {
    const row = object(value)
    return { id: string(row.id), name: string(row.name), status: string(row.status), parent_id: row.parent_id === null ? null : string(row.parent_id) }
  })
}
/** 对比可编辑字段，保留调用者未修改的部门范围等配置，避免只读数据被空值覆盖。 */
export function policyChanges(before: EnterprisePolicy, after: EnterprisePolicy): Partial<EnterprisePolicy> {
  const changes: Partial<EnterprisePolicy> = {}
  if (before.self_build_agents !== after.self_build_agents) changes.self_build_agents = after.self_build_agents
  if (JSON.stringify([...before.self_build_org_unit_ids].sort()) !== JSON.stringify([...after.self_build_org_unit_ids].sort())) changes.self_build_org_unit_ids = [...after.self_build_org_unit_ids]
  if (before.personal_models !== after.personal_models) changes.personal_models = after.personal_models
  if (before.external_sharing !== after.external_sharing) changes.external_sharing = after.external_sharing
  if (before.personal_wecom_channels !== after.personal_wecom_channels) changes.personal_wecom_channels = after.personal_wecom_channels
  if (before.personal_external_channels !== after.personal_external_channels) changes.personal_external_channels = after.personal_external_channels
  if (before.retention_days !== after.retention_days) changes.retention_days = after.retention_days
  return changes
}
