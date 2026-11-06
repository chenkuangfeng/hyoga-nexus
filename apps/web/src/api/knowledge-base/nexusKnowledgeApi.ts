/**
 * Nexus knowledge requests behind the WeKnora-shaped functions of `./index.ts`
 * (openspec 2026-11-06-knowledge-base K0.3 / K1.9).
 *
 * Every call targets `/api/v1/tenants/{effective tenant}/knowledge/...` and converts the answer with
 * `./nexusAdapter`. Features not implemented yet go through {@link planned} (rejects without a request) or
 * {@link plannedEmpty} (resolves an empty WeKnora envelope for read-only lists, so pages render).
 */
import { del, get, getDown, patch, post, postUpload } from '@/utils/request'
import { useAuthStore } from '@/stores/auth'
import {
  PlannedFeatureError, ok, pageToOffset, toNexusBaseInput, toWeKnoraBase, toWeKnoraChunk, toWeKnoraKnowledge,
  toWeKnoraSearchHit,
} from './nexusAdapter'

type Json = Record<string, any>

export function knowledgePath(): string {
  const tenantId = useAuthStore().effectiveTenantId || ''
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge`
}

export function planned(feature: string, stage: string | null = null): Promise<never> {
  return Promise.reject(new PlannedFeatureError(feature, stage))
}

export function plannedEmpty<T>(data: T, extra: Json = {}): Promise<Json> {
  return Promise.resolve(ok(data, extra))
}

export async function listBases(): Promise<Json> {
  const res: Json = await get(`${knowledgePath()}/bases`)
  return ok((res.items || []).map(toWeKnoraBase))
}

export async function createBase(data: Json): Promise<Json> {
  return ok(toWeKnoraBase(await post(`${knowledgePath()}/bases`, toNexusBaseInput(data))))
}

export async function getBase(id: string): Promise<Json> {
  return ok(toWeKnoraBase(await get(`${knowledgePath()}/bases/${encodeURIComponent(id)}`)))
}

export async function updateBase(id: string, data: Json): Promise<Json> {
  const body = toNexusBaseInput(data)
  return ok(toWeKnoraBase(await patch(`${knowledgePath()}/bases/${encodeURIComponent(id)}`, body)))
}

export async function deleteBase(id: string): Promise<Json> {
  await del(`${knowledgePath()}/bases/${encodeURIComponent(id)}`)
  return ok(null)
}

export async function rebuildBase(id: string): Promise<Json> {
  return ok(await post(`${knowledgePath()}/bases/${encodeURIComponent(id)}/rebuild`, {}))
}

export async function listActivity(id: string, limit = 50): Promise<Json> {
  const res: Json = await get(`${knowledgePath()}/bases/${encodeURIComponent(id)}/activity?limit=${limit}`)
  const rows = (res.items || []).map((item: Json) => ({
    id: item.id, tenant_id: '', actor_user_id: item.actor_user_id, actor_role: '', action: item.action,
    scope_type: 'knowledge_base', scope_id: id, target_type: item.target_type, target_id: item.target_id,
    target_user_id: '', request_path: '', request_method: '', outcome: item.result === 'success' ? 'success' : item.result,
    details: item.metadata ?? null, created_at: item.created_at,
  }))
  return { success: true, data: rows }
}

export async function uploadDocument(kbId: string, file: File, fileName: string | undefined,
  onProgress?: (event: any) => void, config?: { signal?: AbortSignal }): Promise<Json> {
  const form = new FormData()
  form.append('file', file)
  if (fileName) form.append('filename', fileName)
  const res: Json = await postUpload(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/documents`, form,
    onProgress, config)
  return ok(toWeKnoraKnowledge(res.document), { deduplicated: res.deduplicated === true })
}

export async function listDocuments(kbId: string, params: Json): Promise<Json> {
  const { offset, limit } = pageToOffset(params.page, params.page_size)
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (params.keyword) query.set('keyword', String(params.keyword))
  const res: Json = await get(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/documents?${query}`)
  return ok((res.items || []).map((doc: Json) => toWeKnoraKnowledge(doc)), {
    total: res.total ?? 0, page: params.page ?? 1, page_size: limit })
}

export async function getDocument(id: string): Promise<Json> {
  return ok(toWeKnoraKnowledge(await get(`${knowledgePath()}/documents/${encodeURIComponent(id)}`)))
}

export async function retryDocument(id: string): Promise<Json> {
  return ok(await post(`${knowledgePath()}/documents/${encodeURIComponent(id)}/retry`, {}))
}

export async function deleteDocument(id: string): Promise<Json> {
  await del(`${knowledgePath()}/documents/${encodeURIComponent(id)}`)
  return ok(null)
}

export function downloadDocument(id: string): Promise<Blob> {
  return getDown(`${knowledgePath()}/documents/${encodeURIComponent(id)}/download`)
}

export async function listChunks(id: string, page: number, pageSize: number): Promise<Json> {
  const { offset, limit } = pageToOffset(page, pageSize)
  const res: Json = await get(`${knowledgePath()}/documents/${encodeURIComponent(id)}/chunks?offset=${offset}&limit=${limit}`)
  return ok((res.items || []).map((chunk: Json) => toWeKnoraChunk(chunk, id)), {
    total: res.total ?? 0, page, page_size: limit })
}

export async function searchBases(query: string, kbIds?: string[], limit = 10): Promise<Json> {
  const body: Json = { query, limit }
  if (kbIds?.length) body.kb_ids = kbIds
  const res: Json = await post(`${knowledgePath()}/search`, body)
  return ok((res.items || []).map(toWeKnoraSearchHit), { degraded: res.degraded || [], ignored: res.ignored || [] })
}
