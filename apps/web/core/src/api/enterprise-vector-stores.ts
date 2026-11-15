/** 当前企业的向量库注册表客户端，严格校验能力目录与脱敏配置响应。 */
import { get, post, put, del } from '../utils/request'

export interface VectorField { name: string; type: 'string' | 'number' | 'boolean'; required: boolean; sensitive: boolean; description: string; default?: unknown; min?: number; enum?: string[] }
export interface VectorType { type: string; display_name: string; status: 'available' | 'planned'; stage: string | null; verified: boolean; connection_fields: VectorField[]; index_fields: VectorField[] }
export interface EnterpriseVectorStore { id: string; name: string; engine: string; builtin: boolean; connection_config: Record<string, unknown>; index_config: Record<string, unknown> }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('admin_response_invalid'); return value as Record<string, unknown> }
function str(value: unknown): string { if (typeof value !== 'string') throw new Error('admin_response_invalid'); return value }
function field(value: unknown): VectorField {
  const row = object(value), kind = str(row.type)
  if (!['string', 'number', 'boolean'].includes(kind) || typeof row.required !== 'boolean') throw new Error('admin_response_invalid')
  if (row.sensitive !== undefined && typeof row.sensitive !== 'boolean') throw new Error('admin_response_invalid')
  const enums = row.enum
  if (enums !== undefined && (!Array.isArray(enums) || !enums.every(item => typeof item === 'string'))) throw new Error('admin_response_invalid')
  return { name: str(row.name), type: kind as VectorField['type'], required: row.required, sensitive: row.sensitive === true, description: typeof row.description === 'string' ? row.description : '', ...(row.default === undefined ? {} : { default: row.default }), ...(typeof row.min === 'number' ? { min: row.min } : {}), ...(enums ? { enum: enums as string[] } : {}) }
}
function path(tenantId: string): string { return `/api/v1/tenants/${encodeURIComponent(tenantId)}/admin/knowledge` }
function store(value: unknown): EnterpriseVectorStore {
  const row = object(value)
  if (typeof row.builtin !== 'boolean') throw new Error('admin_response_invalid')
  return { id: str(row.id), name: str(row.name), engine: str(row.engine), builtin: row.builtin, connection_config: object(row.connection_config), index_config: object(row.index_config) }
}
/** 获取全部能力项；planned 项可展示状态但不得用于提交。 */
export async function listEnterpriseVectorTypes(tenantId: string): Promise<VectorType[]> {
  const response = object(await get(`${path(tenantId)}/vector-store-types`))
  if (!Array.isArray(response.items)) throw new Error('admin_response_invalid')
  return response.items.map(value => {
    const row = object(value), status = str(row.status)
    if (!['available', 'planned'].includes(status) || typeof row.verified !== 'boolean' || !Array.isArray(row.connection_fields) || !Array.isArray(row.index_fields)) throw new Error('admin_response_invalid')
    return { type: str(row.type), display_name: str(row.display_name), status: status as VectorType['status'], stage: row.stage === null ? null : str(row.stage), verified: row.verified, connection_fields: row.connection_fields.map(field), index_fields: row.index_fields.map(field) }
  })
}
/** 列出内置及当前企业注册配置，敏感字段仅以脱敏标记返回。 */
export async function listEnterpriseVectorStores(tenantId: string): Promise<EnterpriseVectorStore[]> {
  const response = object(await get(`${path(tenantId)}/vector-stores`))
  if (!Array.isArray(response.items)) throw new Error('admin_response_invalid')
  return response.items.map(store)
}
/** 创建一个目录中标记 available 的向量库。 */
export async function createEnterpriseVectorStore(tenantId: string, input: { name: string; engine: string; connection_config: Record<string, unknown>; index_config: Record<string, unknown> }): Promise<EnterpriseVectorStore> {
  return store(await post(`${path(tenantId)}/vector-stores`, input))
}
/** 更新名称和配置；脱敏标记会让服务端保留已有密钥。 */
export async function updateEnterpriseVectorStore(tenantId: string, id: string, input: { name: string; connection_config: Record<string, unknown>; index_config: Record<string, unknown> }): Promise<EnterpriseVectorStore> {
  return store(await put(`${path(tenantId)}/vector-stores/${encodeURIComponent(id)}`, input))
}
/** 测试未保存配置，不持久化；仍由服务端复核角色、引擎及目标地址。 */
export async function testEnterpriseVectorDraft(tenantId: string, input: { name: string; engine: string; connection_config: Record<string, unknown>; index_config: Record<string, unknown> }): Promise<{ ok: boolean; message?: string }> {
  const response = object(await post(`${path(tenantId)}/vector-stores/test`, input))
  if (typeof response.ok !== 'boolean') throw new Error('admin_response_invalid')
  return { ok: response.ok, message: typeof response.message === 'string' ? response.message : undefined }
}
/** 测试已保存的内置或企业向量库。 */
export async function testEnterpriseVectorStore(tenantId: string, id: string): Promise<{ ok: boolean; message?: string }> {
  const response = object(await post(`${path(tenantId)}/vector-stores/${encodeURIComponent(id)}/test`, {}))
  if (typeof response.ok !== 'boolean') throw new Error('admin_response_invalid')
  return { ok: response.ok, message: typeof response.message === 'string' ? response.message : undefined }
}
/** 删除企业配置；服务端拒绝删除仍被知识库引用的条目。 */
export async function deleteEnterpriseVectorStore(tenantId: string, id: string): Promise<void> {
  await del(`${path(tenantId)}/vector-stores/${encodeURIComponent(id)}`)
}
