/** 当前企业图存储注册表客户端，仅校验已实现的图存储契约。 */
import { get, post, del } from '../utils/request'

export interface GraphStoreEngine { engine: string; name: string; status: 'available' | 'planned'; stage: string | null; verified: boolean; builtin: boolean }
export interface EnterpriseGraphStore { id: string; name: string; engine: string; builtin: boolean }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('admin_response_invalid'); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('admin_response_invalid'); return value }
function bool(value: unknown): boolean { if (typeof value !== 'boolean') throw new Error('admin_response_invalid'); return value }
function path(tenantId: string): string { return `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge/graph-stores` }
function store(value: unknown): EnterpriseGraphStore { const row = object(value); return { id: string(row.id), name: string(row.name), engine: string(row.engine), builtin: bool(row.builtin) } }
function engine(value: unknown): GraphStoreEngine {
  const row = object(value), status = string(row.status)
  if (!['available', 'planned'].includes(status)) throw new Error('admin_response_invalid')
  return { engine: string(row.engine), name: string(row.name), status: status as GraphStoreEngine['status'], stage: row.stage === null ? null : string(row.stage), verified: bool(row.verified), builtin: bool(row.builtin) }
}
/** 同时获取企业可选图存储及部署级能力目录。 */
export async function listEnterpriseGraphStores(tenantId: string): Promise<{ items: EnterpriseGraphStore[]; engines: GraphStoreEngine[] }> {
  const response = object(await get(path(tenantId)))
  if (!Array.isArray(response.items) || !Array.isArray(response.engines)) throw new Error('admin_response_invalid')
  return { items: response.items.map(store), engines: response.engines.map(engine) }
}
/** 登记 Neo4j 图存储。连接密钥只提交，不由列表回传。 */
export async function createEnterpriseGraphStore(tenantId: string, input: { name: string; engine: string; connection_config: Record<string, unknown> }): Promise<EnterpriseGraphStore> {
  return store(await post(path(tenantId), input))
}
/** 测试尚未保存的 Neo4j 配置。 */
export async function testEnterpriseGraphDraft(tenantId: string, input: { name: string; engine: string; connection_config: Record<string, unknown> }): Promise<{ ok: boolean; message?: string }> {
  const response = object(await post(`${path(tenantId)}/test`, input))
  if (typeof response.ok !== 'boolean') throw new Error('admin_response_invalid')
  return { ok: response.ok, message: typeof response.message === 'string' ? response.message : undefined }
}
/** 测试内置或已登记的图存储。 */
export async function testEnterpriseGraphStore(tenantId: string, id: string): Promise<{ ok: boolean; message?: string }> {
  const response = object(await post(`${path(tenantId)}/${encodeURIComponent(id)}/test`, {}))
  if (typeof response.ok !== 'boolean') throw new Error('admin_response_invalid')
  return { ok: response.ok, message: typeof response.message === 'string' ? response.message : undefined }
}
/** 删除登记项；服务端拒绝删除仍被知识库引用的存储。 */
export async function deleteEnterpriseGraphStore(tenantId: string, id: string): Promise<void> {
  await del(`${path(tenantId)}/${encodeURIComponent(id)}`)
}
