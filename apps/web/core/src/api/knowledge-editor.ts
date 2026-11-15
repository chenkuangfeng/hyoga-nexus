/** 完整编辑器的显式企业客户端。原生 settings 整体替换前合并快照，避免丢失未展示配置。 */
import { get, post, patch } from '../utils/request'
import { toNexusBaseInput, toWeKnoraBase } from './knowledge-base/nexusAdapter'
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('knowledge_editor_response_invalid'); return value as Record<string, unknown> }
/** 编辑前校验归属/维护权限，保留原始 settings 给后续合并使用。 */
export function editableKnowledgeResponse(value: unknown, tenant: string, id?: string, enterpriseOnly = false) {
  const row = object(value)
  if (typeof row.id !== 'string' || (id && row.id !== id) || row.tenant_id !== tenant || !['personal','enterprise'].includes(String(row.ownership)) || (enterpriseOnly && row.ownership !== 'enterprise') || row.can_manage !== true || !['private','tenant','scoped'].includes(String(row.visibility))) throw new Error('knowledge_editor_response_invalid')
  const settings = object(row.settings)
  const chunking = object(row.chunking_config), indexing = object(row.indexing_strategy)
  if (row.shared !== false || !Number.isSafeInteger(row.knowledge_count) || Number(row.knowledge_count) < 0 || !Number.isFinite(chunking.chunk_size) || Number(chunking.chunk_size) <= 0 || !Number.isFinite(chunking.chunk_overlap) || Number(chunking.chunk_overlap) < 0 || ['vector','keyword','graph','wiki'].some(key => typeof indexing[key] !== 'boolean') || (row.embedding_model_id !== null && typeof row.embedding_model_id !== 'string')) throw new Error('knowledge_editor_response_invalid')
  if (typeof row.name !== 'string' || typeof row.description !== 'string' || !['document','faq','wiki'].includes(String(row.type))) throw new Error('knowledge_editor_response_invalid')
  const data: ReturnType<typeof toWeKnoraBase> & { id: string; tenant_id: string; settings_snapshot: Record<string, unknown> } = { ...toWeKnoraBase(row), id: row.id, tenant_id: tenant, ownership: row.ownership, visibility: row.visibility, can_manage: true, settings_snapshot: settings }
  return { success: true as const, data }
}
const base = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}`
export async function getEditableKnowledge(tenant: string, id: string, enterpriseOnly: boolean) { return editableKnowledgeResponse(await get(`${base(tenant)}/${enterpriseOnly ? 'admin/knowledge' : 'knowledge'}/bases/${encodeURIComponent(id)}`), tenant, id, enterpriseOnly) }
/** 沿用完整转换器，额外合并原生未知设置和分块扩展；既有绑定不写入编辑请求。 */
export function knowledgeEditorInput(data: Record<string, unknown>, snapshot: Record<string, unknown> = {}, editing = false) {
  const body: Record<string, unknown> = toNexusBaseInput(data)
  if (data.visibility !== undefined) {
    if (!['private','tenant','scoped'].includes(String(data.visibility))) throw new Error('knowledge_editor_visibility_invalid')
    body.visibility = data.visibility
  }
  const incoming = object(body.settings || {})
  body.settings = { ...snapshot, ...incoming, ...(incoming.chunking_config ? { chunking_config: { ...(snapshot.chunking_config && typeof snapshot.chunking_config === 'object' ? snapshot.chunking_config : {}), ...object(incoming.chunking_config) } } : {}) }
  if (editing) { delete body.type; delete body.vector_store_id; delete body.storage_backend_id }
  return body
}
export async function createEditableKnowledge(tenant: string, data: Record<string, unknown>, enterprise: boolean) {
  const result = await post(`${base(tenant)}/${enterprise ? 'admin/knowledge' : 'knowledge'}/bases`, knowledgeEditorInput(data))
  const response = editableKnowledgeResponse(result, tenant, undefined, enterprise)
  if (response.data.ownership !== (enterprise ? 'enterprise' : 'personal')) throw new Error('knowledge_editor_response_invalid')
  return response
}
export async function updateEditableKnowledge(tenant: string, id: string, data: Record<string, unknown>, snapshot: Record<string, unknown>, enterpriseOnly: boolean) {
  return editableKnowledgeResponse(await patch(`${base(tenant)}/${enterpriseOnly ? 'admin/knowledge' : 'knowledge'}/bases/${encodeURIComponent(id)}`, knowledgeEditorInput(data, snapshot, true)), tenant, id, enterpriseOnly)
}

export interface KnowledgeEditorStorage { id: string; provider: string; name: string }
/** 创建默认绑定来自真实可见存储目录；不读取旧工作台的部署配置接口。 */
export async function listKnowledgeEditorStorage(tenant: string, enterprise = false): Promise<KnowledgeEditorStorage[]> {
  const response = object(await get(`${base(tenant)}/${enterprise ? 'admin/knowledge' : 'knowledge'}/storage-backends`))
  if (!Array.isArray(response.items)) throw new Error('knowledge_editor_response_invalid')
  return response.items.map(value => {
    const row = object(value)
    if (typeof row.id !== 'string' || typeof row.provider !== 'string' || typeof row.name !== 'string') throw new Error('knowledge_editor_response_invalid')
    return { id: row.id, provider: row.provider, name: row.name }
  })
}
