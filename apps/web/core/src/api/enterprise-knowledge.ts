/** 企业知识库目录、内容管理员与读取受众客户端；原生 DTO 校验归属，管理权限由服务端最终决定。 */
import { get, post, del, put } from '../utils/request'
export type EnterpriseKnowledgeType = 'document' | 'faq' | 'wiki'
export type KnowledgeVisibility = 'private' | 'tenant' | 'scoped'
export interface EnterpriseKnowledgeBase {
  id: string; tenant_id: string; name: string; description: string; type: EnterpriseKnowledgeType
  visibility: KnowledgeVisibility; knowledge_count: number; can_manage: boolean
}
export interface KnowledgeMaintainer { user_id: string; display_name: string | null; email: string | null; granted_by: string; granted_at: string }
export interface KnowledgeBaseAudienceItem { kind: 'user' | 'org_unit'; id: string; include_descendants: boolean }
export interface KnowledgeBaseAudience { visibility: KnowledgeVisibility; items: KnowledgeBaseAudienceItem[] }
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
const knowledge = (tenant: string) => `${base(tenant)}/admin/knowledge`
const maintainers = (tenant: string, kb: string) => `${knowledge(tenant)}/bases/${encodeURIComponent(kb)}/maintainers`
/** 原列表受可见性过滤；仅显示当前企业的 enterprise 记录，不声称是完整资产目录。 */
export async function listEnterpriseKnowledgeBases(tenant: string): Promise<EnterpriseKnowledgeBase[]> {
  const rows = array(object(await get(`${knowledge(tenant)}/bases`)).items).flatMap(value => {
    const row = object(value), source = string(row.tenant_id)
    if (!['personal', 'enterprise'].includes(string(row.ownership)) || typeof row.shared !== 'boolean' || (row.shared !== (source !== tenant))) throw invalid()
    return source === tenant && row.ownership === 'enterprise' ? [enterpriseBaseFromResponse(row, tenant)] : []
  })
  if (new Set(rows.map(row => row.id)).size !== rows.length) throw invalid()
  return rows
}
/** 删除当前企业知识库；资源访问立即停用，后台异步清理其内容与索引。 */
export async function deleteEnterpriseKnowledgeBase(tenant: string, kb: string): Promise<void> {
  await del(`${knowledge(tenant)}/bases/${encodeURIComponent(kb)}`)
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
/** 读取当前知识库的完整成员/部门受众；管理权限和企业归属由服务端校验。 */
export function knowledgeBaseAudienceFromResponse(value: unknown): KnowledgeBaseAudience {
  const row = object(value), visibility = string(row.visibility)
  if (!['private', 'tenant', 'scoped'].includes(visibility)) throw invalid()
  const items = array(row.items).map(value => {
    const item = object(value), kind = string(item.kind), id = string(item.id)
    if (!['user', 'org_unit'].includes(kind) || !id.trim() || typeof item.include_descendants !== 'boolean') throw invalid()
    return { kind: kind as KnowledgeBaseAudienceItem['kind'], id, include_descendants: item.include_descendants }
  })
  if (new Set(items.map(item => `${item.kind}:${item.id}`)).size !== items.length) throw invalid()
  return { visibility: visibility as KnowledgeVisibility, items }
}
const audiencePath = (tenant: string, kb: string) => `${knowledge(tenant)}/bases/${encodeURIComponent(kb)}/audience`
export async function getKnowledgeBaseAudience(tenant: string, kb: string): Promise<KnowledgeBaseAudience> {
  return knowledgeBaseAudienceFromResponse(await get(audiencePath(tenant, kb)))
}
/** 整体替换受众；响应必须对应请求的稳定 ID 集合，后端拒绝会破坏智能体绑定的收窄。 */
export async function setKnowledgeBaseAudience(tenant: string, kb: string, items: KnowledgeBaseAudienceItem[]): Promise<KnowledgeBaseAudience> {
  if (!Array.isArray(items) || items.length > 500 || items.some(item => !item || typeof item !== 'object')) throw invalid()
  const keys = items.map(item => `${item.kind}:${item.id}`)
  if (keys.some(key => !key.split(':').slice(1).join(':').trim()) || new Set(keys).size !== keys.length ||
      items.some(item => !['user', 'org_unit'].includes(item.kind) || typeof item.include_descendants !== 'boolean')) throw invalid()
  const result = knowledgeBaseAudienceFromResponse(await put(audiencePath(tenant, kb), { items }))
  if (items.length > 0 && result.visibility !== 'scoped') throw invalid()
  const expected = items.map(item => `${item.kind}:${item.id}:${item.include_descendants}`).sort()
  const received = result.items.map(item => `${item.kind}:${item.id}:${item.include_descendants}`).sort()
  if (expected.length !== received.length || expected.some((item, index) => item !== received[index])) throw invalid()
  return result
}
