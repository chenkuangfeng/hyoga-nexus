/**
 * Nexus long-term memory API (apps/api `/api/v1/tenants/{tenant_id}/native/memory*`).
 *
 * Used by the chat page for the in-conversation draft card (openspec 2026-11-06-memory-evolution E1) and
 * the "forget" action of the used-memory row (B5). Reviewing a draft always goes through the owner's
 * review endpoint: the model can propose drafts but never publish them.
 */
import { del, get, patch, post, put } from '@nexus-web/core/utils/request'
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

// ---------------------------------------------------------------- settings pages
// openspec 2026-11-05-memory-switches (switches, capture) and 2026-11-06-memory-evolution (rules, embedding,
// interests, consolidation, topics, usage). Every request goes to the Nexus `/native` API.


export * from './nexus-memory-types'
import {
  asNumber, asString, memoryListFromResponse, type CaptureSettings, type CaptureUsage, type MemoryDraft, type MemoryEntry,
  memoryDocAffinityFromResponse, type MemoryDocAffinity, type MemoryPreferences, type MemoryTopic, type SpaceMemorySettings, type WriteMode,
} from './nexus-memory-types'

export async function getSpaceMemorySettings(tenantId: string): Promise<SpaceMemorySettings> {
  const data: unknown = await get(`${memoryPath(tenantId)}/memory-settings`)
  if (!isRecord(data) || typeof data.enabled !== 'boolean') throw new Error('Unexpected memory settings response')
  return {
    enabled: data.enabled, write_mode: data.write_mode === 'explicit' ? 'explicit' : 'auto',
    extract_instructions: asString(data.extract_instructions),
    embedding_model_version_id: typeof data.embedding_model_version_id === 'string' ? data.embedding_model_version_id : null,
    interest_threshold: asNumber(data.interest_threshold, 3),
    memory_provider: typeof data.memory_provider === 'string' ? data.memory_provider : null,
    can_edit: data.can_edit === true,
  }
}

export interface SpaceMemorySettingsInput {
  enabled: boolean
  write_mode: WriteMode
  extract_instructions: string
  embedding_model_version_id: string | null
  interest_threshold: number
}

export async function updateSpaceMemorySettings(tenantId: string, body: SpaceMemorySettingsInput): Promise<void> {
  await put(`${memoryPath(tenantId)}/memory-settings`, body)
}

export async function getMemoryPreferences(tenantId: string): Promise<MemoryPreferences> {
  const data: unknown = await get(`${memoryPath(tenantId)}/memory-preferences`)
  if (!isRecord(data) || typeof data.memory_enabled !== 'boolean') throw new Error('Unexpected memory preferences response')
  return {
    memory_enabled: data.memory_enabled, effective: data.effective === true,
    reason: typeof data.reason === 'string' ? data.reason : null,
    write_mode: data.write_mode === 'explicit' ? 'explicit' : 'auto',
  }
}

export async function updateMemoryPreferences(tenantId: string, memoryEnabled: boolean): Promise<void> {
  await put(`${memoryPath(tenantId)}/memory-preferences`, { memory_enabled: memoryEnabled })
}

export async function getCaptureSettings(tenantId: string): Promise<CaptureSettings> {
  const data: unknown = await get(`${memoryPath(tenantId)}/memory-capture`)
  if (!isRecord(data) || typeof data.enabled !== 'boolean') throw new Error('Unexpected capture settings response')
  return {
    enabled: data.enabled,
    model_profile_version_id: typeof data.model_profile_version_id === 'string' ? data.model_profile_version_id : null,
    capacity_policy: data.capacity_policy === 'evict_auto' ? 'evict_auto' : 'reject',
  }
}

export async function updateCaptureSettings(tenantId: string, body: CaptureSettings): Promise<void> {
  await put(`${memoryPath(tenantId)}/memory-capture`, body)
}

export async function getCaptureUsage(tenantId: string): Promise<CaptureUsage> {
  const data: unknown = await get(`${memoryPath(tenantId)}/memory-capture/usage`)
  if (!isRecord(data) || !isRecord(data.usage)) throw new Error('Unexpected capture usage response')
  const usage: Record<string, number> = {}
  for (const [key, value] of Object.entries(data.usage)) if (typeof value === 'number') usage[key] = value
  return { days: asNumber(data.days, 30), calls: asNumber(data.calls), usage }
}

export async function listMemory(tenantId: string): Promise<{ entries: MemoryEntry[]; drafts: MemoryDraft[]; archived: MemoryEntry[] }> {
  return memoryListFromResponse(await get(`${memoryPath(tenantId)}/memory`))
}

/** Review with the full set of options the settings page offers (the chat card only sends a title). */
export async function reviewMemoryDraftWith(tenantId: string, draftId: string,
  body: { approve: boolean; title: string; importance?: number; entry_id?: string; expected_version?: number }): Promise<void> {
  await post(`${memoryPath(tenantId)}/memory-drafts/${encodeURIComponent(draftId)}/review`, body)
}

export async function setMemoryAvailability(tenantId: string, entryId: string,
  body: { enabled?: boolean; valid_until?: string | null; content?: string; title?: string;
    importance?: number; expected_version?: number }): Promise<void> {
  await patch(`${memoryPath(tenantId)}/memory/${encodeURIComponent(entryId)}`, body)
}

/** Clear active entries, pending proposals and automatically tracked topics; archived history is retained. */
export async function clearMemory(tenantId: string): Promise<{ removed: number; drafts: number }> {
  const data: unknown = await del(`${memoryPath(tenantId)}/memory`)
  if (!isRecord(data)) throw new Error('Unexpected memory clear response')
  return { removed: asNumber(data.removed), drafts: asNumber(data.drafts) }
}

export async function restoreMemoryVersion(tenantId: string, entryId: string, version: number,
  expectedVersion: number): Promise<void> {
  await post(`${memoryPath(tenantId)}/memory/${encodeURIComponent(entryId)}/restore`,
    { version, expected_version: expectedVersion })
}

export async function requestConsolidation(tenantId: string): Promise<void> {
  await post(`${memoryPath(tenantId)}/memory-consolidation`, {})
}

export async function listMemoryTopics(tenantId: string): Promise<MemoryTopic[]> {
  const data: unknown = await get(`${memoryPath(tenantId)}/memory-topics`)
  if (!Array.isArray(data)) throw new Error('Unexpected memory topics response')
  return data.filter(isRecord).filter(item => isString(item.id)).map(item => ({
    id: item.id as string, topic: asString(item.topic),
    aliases: Array.isArray(item.aliases) ? item.aliases.filter(isString) : [],
    hits: asNumber(item.hits), threshold: asNumber(item.threshold, 3), promoted: item.promoted === true,
  }))
}

/** Documents the caller's answers cite most (document affinity); only documents that still exist are listed. */
export async function listMemoryDocAffinity(tenantId: string): Promise<MemoryDocAffinity[]> {
  return memoryDocAffinityFromResponse(await get(`${memoryPath(tenantId)}/memory-doc-affinity`))
}

/** Clear one document's counter, or all of the caller's counters when ``documentId`` is omitted. */
export async function clearMemoryDocAffinity(tenantId: string, documentId?: string): Promise<void> {
  const query = documentId ? `?document_id=${encodeURIComponent(documentId)}` : ''
  await del(`${memoryPath(tenantId)}/memory-doc-affinity${query}`)
}

/** Explicit form submission publishes a private memory with server-owned manual provenance. */
export async function createManualMemory(tenantId: string,
  body: { title: string; kind: 'memory' | 'sop' | 'profile' | 'interest' | 'fact' | 'preference' | 'personal_info' | 'task'; content: string; importance: number }): Promise<void> {
  const data: unknown = await post(`${memoryPath(tenantId)}/memory`, body)
  if (!isRecord(data) || data.status !== 'published' || !isString(data.id)) {
    throw new Error('Unexpected memory creation response')
  }
}
