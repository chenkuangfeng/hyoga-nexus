import { get, post, put, del } from '@/utils/request'
import { knowledgePath } from './knowledge-base/nexusKnowledgeApi'

// ===== Types =====

export interface VectorStoreEntity {
  id?: string
  name: string
  engine_type: string
  connection_config: Record<string, any>
  index_config: Record<string, any>
  source: 'env' | 'user'
  readonly: boolean
  tenant_id?: string
  created_at?: string
  updated_at?: string
}

export interface VectorStoreTypeInfo {
  type: string
  display_name: string
  /** Nexus capability state (openspec 2026-11-06-knowledge-base): planned engines have no fields. */
  status?: 'available' | 'planned'
  stage?: string | null
  verified?: boolean
  connection_fields: FieldSchema[]
  index_fields: FieldSchema[]
}

export interface FieldSchema {
  name: string
  type: 'string' | 'number' | 'boolean'
  required: boolean
  sensitive?: boolean
  description?: string
  default?: any
  // Inclusive bounds for number fields (omitempty on the backend). When
  // absent the UI falls back to per-field heuristics (isReplicaField).
  min?: number
  max?: number
  // Closed value set for string fields (e.g. knn_engine ∈ lucene|faiss).
  // When non-empty the UI renders a select instead of a free-text input.
  enum?: string[]
  // Marks a field that cannot change after store creation. Informational
  // for now (edit mode is fully read-only); kept for forward use.
  immutable?: boolean
}

// ===== API Functions =====
// Nexus `/api/v1/tenants/{tenant}/knowledge/vector-store*` (openspec 2026-11-06-knowledge-base K1.6).
// Field names follow the WeKnora page: `engine_type` ↔ Nexus `engine`; the builtin SQLite store is listed
// read-only with `source: 'env'`.

type Json = Record<string, any>

function toEntity(raw: Json): VectorStoreEntity {
  return {
    id: raw.id, name: raw.name, engine_type: raw.engine, connection_config: raw.connection_config || {},
    index_config: raw.index_config || {}, source: raw.builtin ? 'env' : 'user', readonly: raw.builtin === true,
    created_at: raw.created_at, updated_at: raw.updated_at,
  }
}

function testResult(raw: Json): Json {
  return raw.ok ? { success: true, data: raw.details } : { success: false, message: raw.message || raw.code }
}

export function listVectorStoreTypes(): Promise<VectorStoreTypeInfo[]> {
  return get(`${knowledgePath()}/vector-store-types`).then((res: any) => res.items || [])
}

export function listVectorStores(): Promise<{ success: boolean; data: VectorStoreEntity[] }> {
  return get(`${knowledgePath()}/vector-stores`).then((res: any) => ({ success: true, data: (res.items || []).map(toEntity) }))
}

export function createVectorStore(data: Partial<VectorStoreEntity>) {
  return post(`${knowledgePath()}/vector-stores`, { name: data.name, engine: data.engine_type,
    connection_config: data.connection_config || {}, index_config: data.index_config || {} })
    .then((res: any) => ({ success: true, data: toEntity(res) }))
}

export function updateVectorStore(id: string, data: Partial<VectorStoreEntity>) {
  return put(`${knowledgePath()}/vector-stores/${encodeURIComponent(id)}`, { name: data.name,
    connection_config: data.connection_config || {}, index_config: data.index_config || {} })
    .then((res: any) => ({ success: true, data: toEntity(res) }))
}

export function deleteVectorStore(id: string) {
  return del(`${knowledgePath()}/vector-stores/${encodeURIComponent(id)}`).then(() => ({ success: true }))
}

export function testVectorStoreRaw(data: { engine_type: string; connection_config: any }): Promise<any> {
  return post(`${knowledgePath()}/vector-stores/test`, { name: 'test', engine: data.engine_type,
    connection_config: data.connection_config || {} }).then((res: any) => testResult(res))
}

export function testVectorStoreById(id: string): Promise<any> {
  return post(`${knowledgePath()}/vector-stores/${encodeURIComponent(id || 'builtin')}/test`, {})
    .then((res: any) => testResult(res))
}
