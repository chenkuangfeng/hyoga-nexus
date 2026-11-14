/** 企业知识库目录与内容管理员客户端；原生 DTO 校验归属，管理权限由服务端最终决定。 */
import { get, post, del } from '../utils/request'
export type EnterpriseKnowledgeType = 'document' | 'faq' | 'wiki'
export type KnowledgeVisibility = 'private' | 'tenant' | 'scoped'
export interface EnterpriseKnowledgeBase {
  id: string; tenant_id: string; name: string; description: string; type: EnterpriseKnowledgeType
  visibility: KnowledgeVisibility; knowledge_count: number; can_manage: boolean
}
export interface KnowledgeMaintainer { user_id: string; display_name: string | null; email: string | null; granted_by: string; granted_at: string }
const invalid = () => new Error('enterprise_knowledge_response_invalid')
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string') throw invalid(); return value }
function nullable(value: unknown): string | null { return value === null ? null : string(value) }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw invalid(); return value }
/** 目录只接收本企业资源；共享与个人资源在集合解析时过滤。 */
export function enterpriseBaseFromResponse(value: unknown, tenant: string): EnterpriseKnowledgeBase {
  const row = object(value)
  if (row.tenant_id !== tenant || row.ownership !== 'enterprise' || row.shared !== false || typeof row.can_manage !== 'boolean' || !['document', 'faq', 'wiki'].includes(string(row.type)) || !['private', 'tenant', 'scoped'].includes(string(row.visibility)) || !Number.isSafeInteger(row.knowledge_count) || Number(row.knowledge_count) < 0) throw invalid()
  return { id: string(row.id), tenant_id: tenant, name: string(row.name), description: string(row.description), type: row.type as EnterpriseKnowledgeType, visibility: row.visibility as KnowledgeVisibility, knowledge_count: Number(row.knowledge_count), can_manage: row.can_manage }
}
/** 成员可能已离开企业，仍保留服务端管理员记录供撤销；不据此推断当前成员身份。 */
export function knowledgeMaintainersFromResponse(value: unknown): KnowledgeMaintainer[] {
  const rows = array(object(value).items).map(value => {
    const row = object(value)
    return { user_id: string(row.user_id), display_name: nullable(row.display_name), email: nullable(row.email), granted_by: string(row.granted_by), granted_at: string(row.granted_at) }
  })
  if (new Set(rows.map(row => row.user_id)).size !== rows.length) throw invalid()
  return rows
}
const base = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}`
const maintainers = (tenant: string, kb: string) => `${base(tenant)}/admin/knowledge/bases/${encodeURIComponent(kb)}/maintainers`
/** 原列表受可见性过滤；仅显示当前企业的 enterprise 记录，不声称是完整资产目录。 */
export async function listEnterpriseKnowledgeBases(tenant: string): Promise<EnterpriseKnowledgeBase[]> {
  const rows = array(object(await get(`${base(tenant)}/knowledge/bases`)).items).flatMap(value => {
    const row = object(value), source = string(row.tenant_id)
    if (!['personal', 'enterprise'].includes(string(row.ownership)) || typeof row.shared !== 'boolean' || (row.shared !== (source !== tenant))) throw invalid()
    return source === tenant && row.ownership === 'enterprise' ? [enterpriseBaseFromResponse(row, tenant)] : []
  })
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw invalid()
  return rows
}
export async function listKnowledgeMaintainers(tenant: string, kb: string): Promise<KnowledgeMaintainer[]> { return knowledgeMaintainersFromResponse(await get(maintainers(tenant, kb))) }
/** 指定只授予内容维护，返回完整管理员列表；服务端复核活跃成员，已有记录幂等。 */
export async function addKnowledgeMaintainer(tenant: string, kb: string, user: string): Promise<KnowledgeMaintainer[]> {
  const rows = knowledgeMaintainersFromResponse(await post(maintainers(tenant, kb), { user_id: user }))
  if (!rows.some(row => row.user_id === user)) throw invalid()
  return rows
}
/** 204 撤销一项明确记录，不影响成员通过其他授权来源拥有的能力。 */
export async function removeKnowledgeMaintainer(tenant: string, kb: string, user: string): Promise<void> { await del(`${maintainers(tenant, kb)}/${encodeURIComponent(user)}`) }
