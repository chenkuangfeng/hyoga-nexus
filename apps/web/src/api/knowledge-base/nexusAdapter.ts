/**
 * Adapter from Nexus knowledge API responses to the WeKnora shapes the copied knowledge pages read
 * (openspec 2026-11-06-knowledge-base K0.3 / K1.9).
 *
 * The pages under `views/knowledge` were copied from WeKnora and read `{ success, data, total }` envelopes
 * with WeKnora field names. Nexus answers its own shapes (`/api/v1/tenants/{tenant}/knowledge/...`); this
 * module converts them so the pages stay unchanged. Pure functions only (no request helpers), so the
 * mapping is unit tested without the app's path aliases.
 *
 * Features Nexus has not implemented yet reject with {@link PlannedFeatureError} instead of calling an
 * endpoint that does not exist: the UI shows them with a "待实现" badge (capability catalog) and never
 * sends their requests.
 */

export class PlannedFeatureError extends Error {
  readonly planned = true
  constructor(readonly feature: string, readonly stage: string | null = null) {
    super(stage ? `待实现（${stage}）：${feature}` : `待实现：${feature}`)
    this.name = 'PlannedFeatureError'
  }
}

export function isPlannedFeatureError(error: unknown): error is PlannedFeatureError {
  return typeof error === 'object' && error !== null && (error as { planned?: unknown }).planned === true
}

type Json = Record<string, any>

function record(value: unknown): Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Json : {}
}

/** WeKnora success envelope. */
export function ok<T>(data: T, extra: Json = {}): { success: true, data: T } & Json {
  return { success: true, data, ...extra }
}

const PROCESSING = new Set(['pending', 'parsed', 'embedded'])

/** Nexus knowledge base → WeKnora `KnowledgeBase`. */
export function toWeKnoraBase(raw: unknown): Json {
  const kb = record(raw)
  const strategy = record(kb.indexing_strategy)
  const chunking = record(kb.chunking_config)
  const settings = record(kb.settings)
  return {
    ...settings,
    id: kb.id,
    name: kb.name ?? '',
    description: kb.description ?? '',
    type: kb.type ?? 'document',
    tenant_id: kb.tenant_id,
    creator_id: kb.creator_id,
    creator_name: kb.creator_name ?? '',
    embedding_model_id: kb.embedding_model_id ?? '',
    vector_store_id: kb.vector_store_id === 'builtin' ? null : kb.vector_store_id ?? null,
    vector_store_engine_type: kb.vector_engine,
    vector_store_source: kb.vector_store_id === 'builtin' ? 'env' : 'user',
    vector_store_status: 'available',
    storage_backend_id: kb.storage_backend_id === 'builtin' ? null : kb.storage_backend_id ?? null,
    chunking_config: { ...record(settings.chunking_config), chunk_size: chunking.chunk_size,
      chunk_overlap: chunking.chunk_overlap },
    indexing_strategy: {
      vector_enabled: strategy.vector === true,
      keyword_enabled: strategy.keyword === true,
      graph_enabled: strategy.graph === true,
      wiki_enabled: strategy.wiki === true,
    },
    knowledge_count: kb.knowledge_count ?? 0,
    chunk_count: kb.chunk_count ?? 0,
    processing_count: kb.processing_count ?? 0,
    is_processing: kb.is_processing === true,
    is_pinned: false,
    share_count: 0,
    is_shared: kb.shared === true,
    can_edit: kb.can_edit === true,
    created_at: kb.created_at,
    updated_at: kb.updated_at,
  }
}

/** WeKnora create/update payload → Nexus body. Unknown WeKnora blocks go to `settings` unchanged. */
export function toNexusBaseInput(data: Json): Json {
  const config = record(data.config)
  const source = { ...data, ...config }
  const strategy = record(source.indexing_strategy)
  const chunking = record(source.chunking_config)
  const settings: Json = {}
  for (const key of ['image_processing_config', 'summary_model_id', 'vlm_config', 'asr_config', 'extract_config',
    'faq_config', 'wiki_config', 'auto_tag_config', 'profile_config', 'question_generation_config',
    'storage_provider_config']) {
    if (source[key] !== undefined) settings[key] = source[key]
  }
  if (Object.keys(chunking).length) {
    settings.chunking_config = Object.fromEntries(Object.entries(chunking)
      .filter(([key]) => key !== 'chunk_size' && key !== 'chunk_overlap'))
  }
  const body: Json = { name: source.name }
  if (source.description !== undefined) body.description = source.description
  if (source.type !== undefined) body.type = source.type
  if (source.embedding_model_id) body.embedding_model_id = source.embedding_model_id
  if (source.vector_store_id) body.vector_store_id = source.vector_store_id
  if (source.storage_backend_id) body.storage_backend_id = source.storage_backend_id
  if (Object.keys(strategy).length) {
    body.indexing_strategy = { vector: strategy.vector_enabled === true, keyword: strategy.keyword_enabled === true,
      graph: strategy.graph_enabled === true, wiki: strategy.wiki_enabled === true }
  }
  if (chunking.chunk_size !== undefined || chunking.chunk_overlap !== undefined) {
    body.chunking_config = { chunk_size: Number(chunking.chunk_size ?? 800),
      chunk_overlap: Number(chunking.chunk_overlap ?? 120) }
  }
  if (Object.keys(settings).length) body.settings = settings
  return body
}

/** WeKnora `parse_status` of a Nexus document. */
export function parseStatus(doc: Json): string {
  const latest = record(doc.latest_version)
  if (!latest.state) return 'pending'
  if (latest.state === 'failed') return 'failed'
  if (PROCESSING.has(latest.state)) return latest.state === 'pending' ? 'pending' : 'processing'
  return 'completed'
}

/** Nexus document → WeKnora `Knowledge` (a file entry). */
export function toWeKnoraKnowledge(raw: unknown, kbName = ''): Json {
  const doc = record(raw)
  const latest = record(doc.latest_version)
  const current = record(doc.current_version)
  const shown = Object.keys(latest).length ? latest : current
  return {
    id: doc.id,
    knowledge_base_id: doc.kb_id,
    knowledge_base_name: kbName,
    type: 'file',
    title: doc.filename ?? '',
    file_name: doc.filename ?? '',
    file_type: doc.file_type ?? '',
    file_size: shown.size ?? 0,
    file_hash: shown.content_hash ?? '',
    folder_path: '',
    tags: [],
    description: '',
    source: 'upload',
    channel: 'web',
    parse_status: parseStatus(doc),
    summary_status: 'none',
    enable_status: 'enabled',
    error_message: latest.state === 'failed' ? (latest.error_message || latest.error_code || '') : '',
    chunk_count: current.chunk_count ?? 0,
    version: shown.version ?? 0,
    created_at: doc.created_at,
    updated_at: doc.updated_at,
    processed_at: current.updated_at ?? null,
  }
}

/** Nexus chunk → WeKnora `Chunk`. */
export function toWeKnoraChunk(raw: unknown, knowledgeId: string): Json {
  const chunk = record(raw)
  return {
    id: chunk.id,
    knowledge_id: knowledgeId,
    content: chunk.content ?? '',
    chunk_index: chunk.ordinal ?? 0,
    start_at: chunk.char_start ?? 0,
    end_at: chunk.char_end ?? 0,
    is_enabled: true,
    chunk_type: 'text',
    metadata: { page: chunk.page ?? null, section: Array.isArray(chunk.section) ? chunk.section : [] },
  }
}

/** Nexus retrieval-test hit → WeKnora search result row. */
export function toWeKnoraSearchHit(raw: unknown): Json {
  const hit = record(raw)
  return {
    id: hit.chunk_id,
    chunk_id: hit.chunk_id,
    content: hit.content ?? '',
    score: hit.score ?? 0,
    knowledge_id: hit.document_id,
    knowledge_title: hit.filename ?? '',
    knowledge_filename: hit.filename ?? '',
    knowledge_base_id: hit.kb_id,
    knowledge_base_name: hit.kb_name ?? '',
    chunk_index: hit.ordinal ?? 0,
    match_type: hit.channels && Object.keys(hit.channels).length > 1 ? 'hybrid'
      : record(hit.channels).vector !== undefined ? 'vector' : 'keyword',
    channels: record(hit.channels),
    metadata: { page: hit.page ?? null, section: Array.isArray(hit.section) ? hit.section : [] },
  }
}

/** WeKnora page/page_size → Nexus offset/limit. */
export function pageToOffset(page?: number, pageSize?: number): { offset: number, limit: number } {
  const limit = Math.max(1, Math.min(Number(pageSize) || 20, 200))
  const current = Math.max(1, Number(page) || 1)
  return { offset: (current - 1) * limit, limit }
}
