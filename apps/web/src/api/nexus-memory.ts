/**
 * Nexus long-term memory API (apps/api `/api/v1/tenants/{tenant_id}/native/memory*`).
 *
 * Used by the chat page for the in-conversation draft card (openspec 2026-11-06-memory-evolution E1) and
 * the "forget" action of the used-memory row (B5). Reviewing a draft always goes through the owner's
 * review endpoint: the model can propose drafts but never publish them.
 */
import { del, get, post } from '@/utils/request'
import { isRecord, isString } from './native-run-types'

function memoryPath(tenantId: string): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}/native`
}

/** Ids of the caller's drafts still awaiting review in this space. */
export async function listPendingDraftIds(tenantId: string): Promise<Set<string>> {
  const data: unknown = await get(`${memoryPath(tenantId)}/memory`)
  if (!isRecord(data) || !Array.isArray(data.drafts)) throw new Error('Unexpected memory list response')
  return new Set(data.drafts.filter(isRecord).map(draft => draft.id).filter(isString))
}

export interface MemoryReviewResult {
  status: 'published' | 'rejected'
  id?: string
  version?: number
}

/**
 * Publish or reject a draft. A draft that edits an entry names that entry itself, so the card only sends
 * the title. A draft already reviewed elsewhere answers 409 (`MemoryConflict`).
 */
export async function reviewMemoryDraft(tenantId: string, draftId: string, approve: boolean,
  title: string): Promise<MemoryReviewResult> {
  const data: unknown = await post(`${memoryPath(tenantId)}/memory-drafts/${encodeURIComponent(draftId)}/review`,
    { approve, title })
  if (!isRecord(data) || (data.status !== 'published' && data.status !== 'rejected')) {
    throw new Error('Unexpected memory review response')
  }
  return data as unknown as MemoryReviewResult
}

/** Archive a published entry: it leaves the index and future conversations; its history is kept. */
export async function archiveMemoryEntry(tenantId: string, entryId: string): Promise<void> {
  await del(`${memoryPath(tenantId)}/memory/${encodeURIComponent(entryId)}`)
}
