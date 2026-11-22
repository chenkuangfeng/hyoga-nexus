/**
 * Nexus knowledge requests behind the WeKnora-shaped functions of `./index.ts`
 * (openspec 2026-11-06-knowledge-base K0.3 / K1.9).
 *
 * Every call targets `/api/v1/tenants/{effective tenant}/knowledge/...` and converts the answer with
 * `./nexusAdapter`. Features not implemented yet go through {@link planned} (rejects without a request) or
 * {@link plannedEmpty} (resolves an empty WeKnora envelope for read-only lists, so pages render).
 */
import { del, get, getDown, patch, post, postUpload, put } from '@nexus-web/core/utils/request'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  PlannedFeatureError, ok, pageToOffset, toFaqImportProgress, toNexusBaseInput, toNexusFaqInput, toWeKnoraFaqEntry, toWeKnoraBase, toWeKnoraChunk, toWeKnoraKnowledge,
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
  if (params.tag_ids) query.set('tag_ids', String(params.tag_ids))
  if (params.file_type) query.set('file_type', String(params.file_type))
  if (params.folder_path !== undefined) {
    query.set('folder_path', String(params.folder_path))
    query.set('folder_recursive', String(params.folder_recursive === true))
  }
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

// ---------------------------------------------------------------- FAQ (K3)

function faqPath(kbId: string): string {
  return `${knowledgePath()}/bases/${encodeURIComponent(kbId)}/faq`
}

export async function listFaq(kbId: string, params: Json): Promise<Json> {
  const limit = Math.max(1, Math.min(Number(params.page_size) || 20, 200))
  const offset = (Math.max(1, Number(params.page) || 1) - 1) * limit
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (params.keyword) query.set('keyword', String(params.keyword))
  if (params.tag_ids) query.set('tag_ids', String(params.tag_ids))
  if (typeof params.is_enabled === 'boolean') query.set('is_enabled', String(params.is_enabled))
  const res: Json = await get(`${faqPath(kbId)}/entries?${query}`)
  return ok({ data: (res.items || []).map(toWeKnoraFaqEntry), total: res.total ?? 0 })
}

export async function createFaq(kbId: string, data: Json): Promise<Json> {
  return ok(toWeKnoraFaqEntry(await post(`${faqPath(kbId)}/entries`, toNexusFaqInput(data))))
}

export async function updateFaq(kbId: string, entryId: string, data: Json): Promise<Json> {
  return ok(toWeKnoraFaqEntry(await put(`${faqPath(kbId)}/entries/${encodeURIComponent(entryId)}`, toNexusFaqInput(data))))
}

export async function updateFaqFields(kbId: string, ids: string[], fields: Json): Promise<Json> {
  return ok(await patch(`${faqPath(kbId)}/entries`, { ids, ...fields }))
}

export async function deleteFaq(kbId: string, ids: string[]): Promise<Json> {
  return ok(await post(`${faqPath(kbId)}/entries/delete`, { ids }))
}

const importResults = new Map<string, Json>()

/** Import entries. The server answers at once; the result is kept under a task id so the progress UI shows it. */
export async function importFaq(kbId: string, entries: Json[], mode: 'append' | 'replace'): Promise<Json> {
  const result: Json = await post(`${faqPath(kbId)}/import`, { entries: entries.map(toNexusFaqInput), mode })
  const taskId = `nexus-faq-${Date.now()}-${importResults.size}`
  importResults.set(taskId, toFaqImportProgress(taskId, kbId, entries.length, result))
  return ok({ task_id: taskId })
}

export function faqImportProgress(taskId: string): Promise<Json> {
  const progress = importResults.get(taskId)
  return progress ? Promise.resolve(ok(progress)) : Promise.reject(new PlannedFeatureError('导入任务已过期'))
}

export async function searchFaq(kbId: string, queryText: string, matchCount = 10): Promise<Json> {
  const res: Json = await post(`${faqPath(kbId)}/search`, { query_text: queryText, match_count: matchCount })
  return ok((res.items || []).map((hit: Json) => ({
    ...toWeKnoraFaqEntry({ id: hit.document_id, kb_id: hit.kb_id, standard_question: hit.filename,
      answers: String(hit.content || '').split('答：').slice(1) }),
    score: hit.score, match_type: Object.keys(hit.channels || {}).length > 1 ? 'hybrid'
      : hit.channels?.vector !== undefined ? 'vector' : 'keyword' })))
}

export function exportFaq(kbId: string, format: 'csv' | 'json'): Promise<Blob> {
  return getDown(`${faqPath(kbId)}/export?format=${format}`)
}

// ---------------------------------------------------------------- organization (K5)

export async function listTags(kbId: string, params: Json = {}): Promise<Json> {
  const query = params.keyword ? `?keyword=${encodeURIComponent(String(params.keyword))}` : ''
  const res: Json = await get(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/tags${query}`)
  const items = res.items || []
  return ok({ data: items, total: items.length }, { total: items.length })
}

export async function createTag(kbId: string, data: Json): Promise<Json> {
  return ok(await post(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/tags`, data))
}

export async function updateTag(kbId: string, tagId: string, data: Json): Promise<Json> {
  return ok(await put(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/tags/${encodeURIComponent(tagId)}`, data))
}

export async function deleteTag(kbId: string, tagId: string, force: boolean): Promise<Json> {
  return ok(await del(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/tags/${encodeURIComponent(tagId)}?force=${force}`))
}

export async function setDocumentTags(updates: Record<string, string[]>): Promise<Json> {
  return ok(await put(`${knowledgePath()}/document-tags`, { updates }))
}

export async function organizeDocuments(kbId: string, ids: string[], changes: Json): Promise<Json> {
  return ok(await patch(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/documents`, { ids, ...changes }))
}

export async function folderTree(kbId: string): Promise<Json> {
  return ok(await get(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/folders`))
}

export async function createFolder(kbId: string, path: string): Promise<string> {
  const result = await post<{ path: string }>(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/folders`, { path })
  if (typeof result.path !== 'string' || !result.path) throw new Error('Invalid folder response')
  return result.path
}

export async function renameFolder(kbId: string, source: string, target: string): Promise<Json> {
  return ok(await put(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/folders`, { source, target }))
}

export async function togglePin(kbId: string): Promise<Json> {
  return ok(await put(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/pin`, {}))
}

export async function generateProfile(kbId: string): Promise<Json> {
  return ok(await post(`${knowledgePath()}/bases/${encodeURIComponent(kbId)}/profile/generate`, {}))
}
