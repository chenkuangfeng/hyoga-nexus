/** 企业智能体管理客户端。复用既有接口，显式校验归属、维护权和完整草稿，拒绝串企业响应。 */
import { get, post, put, del } from '../utils/request'
import type { AgentDraftInput, NexusAgent } from './nexus-agents'
const invalid = () => new Error('agents_response_invalid')
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string') throw invalid(); return value }
function nullable(value: unknown): string | null { return value === null ? null : string(value) }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw invalid(); return value }
/** 校验完整 DTO，未列出的资源绑定原样保留；服务端 can_maintain 是编辑入口依据。 */
export function enterpriseAgentFromResponse(value: unknown, tenant: string): NexusAgent {
  const row = object(value)
  if (row.tenant_id !== tenant || row.ownership !== 'enterprise' || typeof row.can_maintain !== 'boolean' || !['draft', 'published', 'archived'].includes(string(row.status)) || !Number.isInteger(row.version_counter) || Number(row.version_counter) < 0) throw invalid()
  return { id: string(row.id), tenant_id: tenant, ownership: 'enterprise', can_maintain: row.can_maintain,
    name: string(row.name), description: string(row.description), status: string(row.status), runtime_type: string(row.runtime_type), instructions: string(row.instructions),
    published_version_id: nullable(row.published_version_id), model_profile_version_id: nullable(row.model_profile_version_id), version_counter: Number(row.version_counter), budgets: object(row.budgets),
    resource_bindings: array(row.resource_bindings).map(value => { const binding = object(value); return { kind: string(binding.kind), resource_id: string(binding.resource_id), resource_version_id: nullable(binding.resource_version_id), source_tenant_id: string(binding.source_tenant_id), config: object(binding.config) } }),
    created_at: string(row.created_at), updated_at: string(row.updated_at) }
}
const base = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}`
/** 接口还返回个人资源；仅接受本企业记录并筛出 enterprise，不把可见列表冒充完整目录。 */
export async function listEnterpriseAgents(tenant: string): Promise<NexusAgent[]> {
  return array(await get(`${base(tenant)}/agents`)).flatMap(value => {
    const row = object(value)
    if (row.tenant_id !== tenant || !['personal', 'enterprise'].includes(string(row.ownership))) throw invalid()
    return row.ownership === 'enterprise' ? [enterpriseAgentFromResponse(row, tenant)] : []
  })
}
export async function getEnterpriseAgent(tenant: string, id: string): Promise<NexusAgent> {
  const row = enterpriseAgentFromResponse(await get(`${base(tenant)}/agents/${encodeURIComponent(id)}`), tenant)
  if (row.id !== id || !row.can_maintain || row.status === 'archived') throw invalid()
  return row
}
export async function createEnterpriseAgent(tenant: string, body: AgentDraftInput): Promise<NexusAgent> { return enterpriseAgentFromResponse(await post(`${base(tenant)}/admin/agents`, body), tenant) }
export async function updateEnterpriseAgent(tenant: string, id: string, body: AgentDraftInput): Promise<NexusAgent> {
  const row = enterpriseAgentFromResponse(await put(`${base(tenant)}/agents/${encodeURIComponent(id)}`, body), tenant)
  if (row.id !== id) throw invalid()
  return row
}
/** 发布结果必须指向本次草稿；发布失败保留草稿，由编辑器更新重试。 */
export async function publishEnterpriseAgent(tenant: string, id: string): Promise<void> {
  const row = object(await post(`${base(tenant)}/agents/${encodeURIComponent(id)}/publish`, {}))
  if (row.id !== id || !Number.isInteger(row.version) || Number(row.version) < 1) throw invalid()
}
export async function archiveEnterpriseAgent(tenant: string, id: string): Promise<void> { await del(`${base(tenant)}/agents/${encodeURIComponent(id)}`) }

export interface AgentKnowledgeChoice { id: string; tenant_id: string; name: string; description: string; shared: boolean; knowledge_count: number; ownership: 'personal' | 'enterprise' }
/** 从原生知识库 DTO 获取候选，避免旧适配器丢失 ownership；共享来源的 tenant_id 用于绑定。 */
export async function listAgentKnowledgeChoices(tenant: string, enterprise: boolean): Promise<AgentKnowledgeChoice[]> {
  return array(object(await get(`${base(tenant)}/knowledge/bases`)).items).map(value => {
    const row = object(value)
    if (!['personal', 'enterprise'].includes(string(row.ownership)) || typeof row.shared !== 'boolean' || !Number.isInteger(row.knowledge_count) || Number(row.knowledge_count) < 0) throw invalid()
    const ownership = row.ownership as 'personal' | 'enterprise'
    const choice = { id: string(row.id), tenant_id: string(row.tenant_id), name: string(row.name), description: string(row.description), shared: row.shared, knowledge_count: Number(row.knowledge_count), ownership }
    if (!choice.shared && choice.tenant_id !== tenant) throw invalid()
    return choice
  }).filter(row => !enterprise || row.ownership === 'enterprise')
}
