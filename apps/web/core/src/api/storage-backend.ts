import { get, post, del } from '@nexus-web/core/utils/request'
import { knowledgePath } from './knowledge-base/nexusKnowledgeApi'
import { PlannedFeatureError } from './knowledge-base/nexusAdapter'

export interface StorageBackendConfig {
  mode?: string
  endpoint?: string
  region?: string
  access_key_id?: string
  secret_access_key?: string
  bucket_name?: string
  path_prefix?: string
  app_id?: string
  use_ssl?: boolean
  force_path_style?: boolean
  use_temp_bucket?: boolean
  temp_bucket_name?: string
  temp_region?: string
}

export interface StorageBackend {
  id: string
  tenant_id?: string
  name: string
  provider: string
  config: StorageBackendConfig
  source: 'user' | 'env'
  status: 'active' | 'disabled'
  legacy_alias?: boolean
  created_at?: string
  updated_at?: string
}

export interface StorageBackendListResponse {
  success: boolean
  data: StorageBackend[]
  default_storage_backend_id?: string | null
}

// Nexus `/api/v1/tenants/{tenant}/knowledge/storage-backends` (openspec 2026-11-06-knowledge-base K1.6).
// The builtin local directory is listed read-only (`source: 'env'`); only `local` is implemented, other
// providers are planned and listed by the capability catalog.
type Json = Record<string, any>

function toBackend(raw: Json): StorageBackend {
  return { id: raw.id, name: raw.name, provider: raw.provider, config: raw.config || {},
    source: raw.builtin ? 'env' : 'user', status: 'active', created_at: raw.created_at, updated_at: raw.updated_at }
}

export const listStorageBackends = (): Promise<StorageBackendListResponse> =>
  get(`${knowledgePath()}/storage-backends`).then((res: any) => ({
    success: true, data: (res.items || []).map(toBackend), default_storage_backend_id: 'builtin' }))
export const listStorageBackendTypes = (): Promise<{ success: boolean; data: string[] }> =>
  get(`${knowledgePath()}/capabilities`).then((res: any) => ({ success: true, data: (res.items || [])
    .filter((item: Json) => item.group === 'storage_provider').map((item: Json) => item.key) }))
export const createStorageBackend = (data: Partial<StorageBackend>) =>
  post(`${knowledgePath()}/storage-backends`, { name: data.name, provider: data.provider, config: data.config || {} })
    .then((res: any) => ({ success: true, data: toBackend(res) }))
export const updateStorageBackend = (id: string, data: Partial<StorageBackend>) => {
  void id; void data
  return Promise.reject(new PlannedFeatureError('编辑存储后端', 'K5'))
}
export const deleteStorageBackend = (id: string) =>
  del(`${knowledgePath()}/storage-backends/${encodeURIComponent(id)}`).then(() => ({ success: true }))
export const setDefaultStorageBackend = (id: string) => {
  void id
  return Promise.reject(new PlannedFeatureError('默认存储后端', 'K5'))
}
export const testStorageBackend = (data: Partial<StorageBackend>) => {
  void data
  return Promise.reject(new PlannedFeatureError('未保存配置的存储连接测试', 'K5'))
}
export const testStorageBackendByID = (id: string) =>
  post(`${knowledgePath()}/storage-backends/${encodeURIComponent(id || 'builtin')}/test`, {})
    .then((res: any) => res.ok ? { success: true, data: res.details } : { success: false, message: res.message || res.code })
