/** 企业渠道与 MCP 连接客户端；只使用 Nexus 租户作用域接口，响应在消费前校验。 */
import { del, get, patch, post } from '../utils/request'

export type ChannelKind = 'wecom_app' | 'wecom_bot' | 'wechat' | 'qq'
export type ChannelStatus = 'active' | 'binding' | 'pending_review' | 'rejected' | 'disabled' | 'expired'
export interface AgentChannel {
  id: string; agent_id: string; kind: ChannelKind; status: ChannelStatus; name: string
  owner_user_id: string; bound: boolean; review_note: string | null; created_at?: string; updated_at?: string
}
export interface WecomAgentApp { id: string; name: string; purpose: string; nexus_agent_id: string | null; status: string }
export interface Endpoint {
  id: string; tenant_id: string; name: string; description: string; enabled: boolean
  tool_allowlist: string[]; kb_ids: string[]; created_by: string
}
export interface EndpointInput { name: string; description: string; tool_allowlist: string[]; kb_ids: string[] }
export interface KnowledgeChoice { id: string; name: string }

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('connection_response_invalid')
  return value as Record<string, unknown>
}
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('connection_response_invalid'); return value }
function boolean(value: unknown): boolean { if (typeof value !== 'boolean') throw new Error('connection_response_invalid'); return value }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error('connection_response_invalid'); return value }
function strings(value: unknown): string[] { return array(value).map(string) }
/** 校验渠道响应，仅保留非秘密字段；格式不符时抛出 connection_response_invalid。 */
export function channelFromResponse(value: unknown): AgentChannel {
  const row = object(value)
  if (!['wecom_app', 'wecom_bot', 'wechat', 'qq'].includes(string(row.kind)) || !['active', 'binding', 'pending_review', 'rejected', 'disabled', 'expired'].includes(string(row.status))) throw new Error('connection_response_invalid')
  return { id: string(row.id), agent_id: string(row.agent_id), kind: row.kind as ChannelKind, status: row.status as ChannelStatus,
    name: string(row.name), owner_user_id: string(row.owner_user_id), bound: boolean(row.bound), review_note: row.review_note == null ? null : string(row.review_note),
    ...(row.created_at === undefined ? {} : { created_at: string(row.created_at) }), ...(row.updated_at === undefined ? {} : { updated_at: string(row.updated_at) }) }
}
/** 校验企业连接元数据并剔除 token，避免列表状态持有凭据。 */
export function endpointFromResponse(value: unknown): Endpoint {
  const row = object(value)
  // 列表和表单状态仅接收非秘密字段，创建/轮换响应的 token 单独短时消费。
  return { id: string(row.id), tenant_id: string(row.tenant_id), name: string(row.name), description: string(row.description), enabled: boolean(row.enabled),
    tool_allowlist: strings(row.tool_allowlist), kb_ids: strings(row.kb_ids), created_by: string(row.created_by) }
}
function tenant(tenantId: string): string { return `/api/v1/tenants/${encodeURIComponent(tenantId)}` }
function channel(tenantId: string, id: string): string { return `${tenant(tenantId)}/channels/${encodeURIComponent(id)}` }
function endpoint(tenantId: string, id = '', admin = false): string { return `${tenant(tenantId)}${admin ? '/admin' : ''}/mcp-endpoints${id ? `/${encodeURIComponent(id)}` : ''}` }

/** 渠道与平台核验状态来自同一次读取；未核验的渠道不可创建。 */
export async function listAgentChannels(tenantId: string, agentId: string) {
  const data = object(await get(`${tenant(tenantId)}/agents/${encodeURIComponent(agentId)}/channels`))
  const items = array(data.items).map(channelFromResponse)
  if (items.some(row => row.agent_id !== agentId)) throw new Error('connection_response_invalid')
  return { items, unverified: strings(data.unverified_kinds) }
}
/** 为指定企业和智能体创建渠道；策略、维护权及类型核验由服务端执行。 */
export async function createAgentChannel(tenantId: string, agentId: string, input: { kind: ChannelKind; name: string; wecom_app_id?: string }) {
  return channelFromResponse(await post(`${tenant(tenantId)}/agents/${encodeURIComponent(agentId)}/channels`, input))
}
/** 停用当前企业内的渠道；服务端检查维护权限。 */
export async function disableAgentChannel(tenantId: string, id: string) { await post(`${channel(tenantId, id)}/disable`, {}) }
/** 永久删除渠道；调用方须先确认，服务端检查维护权限。 */
export async function deleteAgentChannel(tenantId: string, id: string) { await del(channel(tenantId, id)) }
/** 启动所有者微信绑定并返回二维码原始内容；必须在本地编码，不发送第三方。 */
export async function beginWechatBinding(tenantId: string, id: string): Promise<string> {
  const content = string(object(await post(`${channel(tenantId, id)}/wechat/qr`, {})).qrcode_url)
  if (!content || content.length > 4096) throw new Error('connection_response_invalid')
  return content
}
/** 读取一次绑定状态；轮询调度与离开页面后的清理由调用方负责。 */
export async function pollWechatBinding(tenantId: string, id: string) {
  const data = object(await get(`${channel(tenantId, id)}/wechat/status`))
  return { status: string(data.status), channel: data.channel ? channelFromResponse(data.channel) : null }
}
/** 企业智能体管理员读取渠道总览或指定状态的审核队列。 */
export async function listEnterpriseChannels(tenantId: string, status?: ChannelStatus): Promise<AgentChannel[]> {
  const query = status ? `?status_filter=${encodeURIComponent(status)}` : ''
  return array(object(await get(`${tenant(tenantId)}/admin/channels${query}`)).items).map(channelFromResponse)
}
/** 读取调用者可见智能体的名称映射，供渠道总览显示可读名称而不展示 ID。 */
export async function listChannelAgentNames(tenantId: string): Promise<Array<{ id: string; name: string }>> {
  return array(await get(`${tenant(tenantId)}/admin/agents`)).map(value => {
    const row = object(value)
    if (row.tenant_id !== tenantId || !['personal', 'enterprise'].includes(string(row.ownership))) throw new Error('connection_response_invalid')
    return { id: string(row.id), name: string(row.name) }
  })
}
/** 审核待处理的企业渠道；拒绝时服务端要求提供原因。 */
export async function reviewEnterpriseChannel(tenantId: string, id: string, input: { approve: boolean; note?: string }): Promise<AgentChannel> {
  const row = channelFromResponse(await post(`${tenant(tenantId)}/admin/channels/${encodeURIComponent(id)}/review`, input))
  if (row.id !== id || row.status !== (input.approve ? 'active' : 'rejected')) throw new Error('connection_response_invalid')
  return row
}
/** 读取当前企业内调用者的 API 权限，不根据角色名称推断权限。 */
export async function fetchConnectionPermissions(tenantId: string): Promise<string[]> {
  return strings(object(await get(`${tenant(tenantId)}/me/permissions`)).apis)
}
/** 读取当前企业的个人外部渠道策略，失败时调用方应禁止创建。 */
export async function fetchChannelPolicy(tenantId: string) {
  return { personal_external_channels: boolean(object(await get(`${tenant(tenantId)}/admin/policy`)).personal_external_channels) }
}
/** 读取组织配置中的应用元数据，要求 org:manage；不返回应用秘密。 */
export async function fetchWecomApps(tenantId: string): Promise<WecomAgentApp[]> {
  return array(object(await get(`${tenant(tenantId)}/admin/wecom`)).apps).map(value => {
    const row = object(value)
    return { id: string(row.id), name: string(row.name), purpose: string(row.purpose), status: string(row.status), nexus_agent_id: row.nexus_agent_id == null ? null : string(row.nexus_agent_id) }
  })
}
/** 读取当前企业连接元数据；拒绝混入其他企业的响应。 */
export async function listEndpoints(tenantId: string, admin = false): Promise<Endpoint[]> {
  const rows = array(await get(endpoint(tenantId, '', admin))).map(endpointFromResponse)
  if (rows.some(row => row.tenant_id !== tenantId)) throw new Error('connection_response_invalid')
  return rows
}
/** 创建企业连接并分离一次性令牌；调用方仅在当前弹窗内存中保留令牌。 */
export async function createEndpoint(tenantId: string, input: EndpointInput, admin = false) {
  const data = object(await post(endpoint(tenantId, '', admin), input))
  return { endpoint: endpointFromResponse(data), token: string(data.token) }
}
/** 更新企业连接配置或启用状态；服务端要求 tools:manage。 */
export async function updateEndpoint(tenantId: string, id: string, input: Partial<EndpointInput> & { enabled?: boolean }, admin = false): Promise<Endpoint> {
  return endpointFromResponse(await patch(endpoint(tenantId, id, admin), input))
}
/** 删除企业连接及其令牌；调用方须先确认。 */
export async function deleteEndpoint(tenantId: string, id: string, admin = false) { await del(endpoint(tenantId, id, admin)) }
/** 立即使旧令牌失效并返回一次性新令牌；不得写入持久存储。 */
export async function rotateEndpointToken(tenantId: string, id: string, admin = false) {
  const data = object(await post(`${endpoint(tenantId, id, admin)}/rotate-token`, {}))
  return { endpoint: endpointFromResponse(data), token: string(data.token) }
}
/** 吊销企业连接现有令牌；不会生成替代令牌。 */
export async function revokeEndpointToken(tenantId: string, id: string, admin = false) { await post(`${endpoint(tenantId, id, admin)}/revoke-token`, {}) }
/** 读取可选知识库名称与稳定 ID，避免让用户填写内部标识。 */
export async function listEndpointKnowledge(tenantId: string, admin = false): Promise<KnowledgeChoice[]> {
  return array(object(await get(`${tenant(tenantId)}${admin ? '/admin' : ''}/knowledge/bases`)).items).map(value => {
    const row = object(value); return { id: string(row.id), name: string(row.name) }
  })
}
/** 与平台 MCP 无状态只读工具面一致；服务端仍逐次校验白名单与知识库范围。 */
export const ENDPOINT_TOOLS = ['grep_chunks', 'document_outline', 'query_knowledge_graph', 'search_knowledge', 'read_document', 'list_documents', 'web_search', 'web_fetch', 'load_skill', 'read_skill_file', 'skill_search', 'read_memory', 'search_memory', 'search_conversations', 'read_conversation'] as const
