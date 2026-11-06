/**
 * Types and response parsing for the Nexus memory API (`nexus-memory.ts`). Pure: no request helpers, so
 * the parsing rules are unit tested without the app's path aliases.
 */
import { isRecord, isString } from './native-run-types'

export type WriteMode = 'explicit' | 'auto'

export interface SpaceMemorySettings {
  enabled: boolean
  write_mode: WriteMode
  extract_instructions: string
  embedding_model_version_id: string | null
  interest_threshold: number
  memory_provider: string | null
  can_edit: boolean
}

export interface MemoryPreferences {
  memory_enabled: boolean
  effective: boolean
  reason: string | null
  write_mode: WriteMode
}

export interface CaptureSettings {
  enabled: boolean
  model_profile_version_id: string | null
  capacity_policy: 'reject' | 'evict_auto'
}

export interface CaptureUsage {
  days: number
  calls: number
  usage: Record<string, number>
}

export interface MemoryEntry {
  id: string
  title: string
  kind: string
  project: string
  version: number
  enabled: boolean
  valid_until: string | null
  topic: string
  importance: number
}

export interface MemoryHint {
  entry_id: string
  title: string
  score?: number
}

export interface MemoryDraft {
  id: string
  kind: string
  diff: string
  origin: string
  base_version: number | null
  target_entry_id: string | null
  topic: string
  importance: number | null
  confidence: string | null
  valid_until: string | null
  evidence: { message_id?: string; sequence?: number; quote: string }[]
  conflicts: MemoryHint[]
  similar: MemoryHint[]
  /** Entries a merge draft archives when published. */
  merges: { id: string; title: string; version: number }[]
}

export interface MemoryTopic {
  id: string
  topic: string
  aliases: string[]
  hits: number
  threshold: number
  promoted: boolean
}

export function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

export function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function hints(value: unknown): MemoryHint[] {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map(item => ({
    entry_id: asString(item.entry_id), title: asString(item.title),
    ...(typeof item.score === 'number' ? { score: item.score } : {}),
  })).filter(item => item.entry_id)
}

/** Validate and normalize `GET /native/memory`; malformed items are dropped, not trusted. */
export function memoryListFromResponse(data: unknown): { entries: MemoryEntry[]; drafts: MemoryDraft[] } {
  if (!isRecord(data) || !Array.isArray(data.entries) || !Array.isArray(data.drafts)) {
    throw new Error('Unexpected memory list response')
  }
  const entries = data.entries.filter(isRecord).filter(item => isString(item.id)).map(item => ({
    id: item.id as string, title: asString(item.title), kind: asString(item.kind, 'memory'),
    project: asString(item.project), version: asNumber(item.version, 1), enabled: item.enabled !== false,
    valid_until: typeof item.valid_until === 'string' ? item.valid_until : null,
    topic: asString(item.topic), importance: asNumber(item.importance, 3),
  }))
  const drafts = data.drafts.filter(isRecord).filter(item => isString(item.id)).map(item => {
    const annotations = isRecord(item.annotations) ? item.annotations : {}
    const merge = isRecord(annotations.merge) && Array.isArray(annotations.merge.archive) ? annotations.merge.archive : []
    return {
      id: item.id as string, kind: asString(item.kind, 'memory'), diff: asString(item.diff), origin: asString(item.origin),
      base_version: typeof item.base_version === 'number' ? item.base_version : null,
      target_entry_id: typeof item.target_entry_id === 'string' ? item.target_entry_id : null,
      topic: asString(item.topic), importance: typeof item.importance === 'number' ? item.importance : null,
      confidence: typeof item.confidence === 'string' ? item.confidence : null,
      valid_until: typeof item.valid_until === 'string' ? item.valid_until : null,
      evidence: Array.isArray(item.evidence)
        ? item.evidence.filter(isRecord).map(e => ({
          quote: asString(e.quote),
          ...(typeof e.sequence === 'number' ? { sequence: e.sequence } : {}),
          ...(typeof e.message_id === 'string' ? { message_id: e.message_id } : {}),
        })).filter(e => e.quote)
        : [],
      conflicts: hints(annotations.conflict),
      similar: hints(annotations.similar),
      merges: merge.filter(isRecord).map(m => ({ id: asString(m.id), title: asString(m.title), version: asNumber(m.version, 1) }))
        .filter(m => m.id),
    }
  })
  return { entries, drafts }
}

