/** 当前企业知识文件存储配置。能力受服务端目录与权限策略约束。 */
import { get, post, del } from '../utils/request'

export interface EnterpriseStorageBackend {
  id: string
  name: string
  provider: string
  builtin: boolean
  config: Record<string, unknown>
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('admin_response_invalid')
  return value as Record<string, unknown>
}
function backend(value: unknown): EnterpriseStorageBackend {
  const row = object(value), config = object(row.config)
  if (typeof row.id !== 'string' || typeof row.name !== 'string' || typeof row.provider !== 'string' || typeof row.builtin !== 'boolean') throw new Error('admin_response_invalid')
  return { id: row.id, name: row.name, provider: row.provider, builtin: row.builtin, config }
}
function tenantPath(tenantId: string): string { return `/api/v1/tenants/${encodeURIComponent(tenantId)}/admin/knowledge/storage-backends` }
/** 列出当前企业可见的内置与自定义存储后端。 */
export async function listEnterpriseStorageBackends(tenantId: string): Promise<EnterpriseStorageBackend[]> {
  const response = object(await get(tenantPath(tenantId)))
  if (!Array.isArray(response.items)) throw new Error('admin_response_invalid')
  return response.items.map(backend)
}
/** 添加已实现的存储提供方配置；服务端会验证目标和连接。 */
export async function createEnterpriseStorageBackend(tenantId: string, name: string, root: string): Promise<EnterpriseStorageBackend> {
  return backend(await post(tenantPath(tenantId), { name, provider: 'local', config: { root } }))
}
/** 删除自定义配置；若知识库正在使用，服务端会拒绝。 */
export async function deleteEnterpriseStorageBackend(tenantId: string, id: string): Promise<void> {
  await del(`${tenantPath(tenantId)}/${encodeURIComponent(id)}`)
}
/** 测试已保存后端，返回后端提供的连通结果。 */
export async function testEnterpriseStorageBackend(tenantId: string, id: string): Promise<{ ok: boolean; message?: string }> {
  const response = object(await post(`${tenantPath(tenantId)}/${encodeURIComponent(id)}/test`, {}))
  if (typeof response.ok !== 'boolean') throw new Error('admin_response_invalid')
  return { ok: response.ok, message: typeof response.message === 'string' ? response.message : undefined }
}
