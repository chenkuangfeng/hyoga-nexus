import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  PlannedFeatureError, isPlannedFeatureError, pageToOffset, parseStatus, toNexusBaseInput, toWeKnoraBase,
  toFaqImportProgress, toNexusFaqInput, toWeKnoraChunk, toWeKnoraFaqEntry, toWeKnoraKnowledge, toWeKnoraSearchHit,
} from './nexusAdapter.ts'

test('knowledge base maps to WeKnora names and keeps settings blocks', () => {
  const kb = toWeKnoraBase({
    id: 'k1', name: '手册', type: 'document', vector_store_id: 'builtin', vector_engine: 'sqlite',
    indexing_strategy: { vector: true, keyword: true, graph: false, wiki: false },
    chunking_config: { chunk_size: 500, chunk_overlap: 50 }, settings: { faq_config: { index_mode: 'x' } },
    knowledge_count: 3, can_edit: true,
  })
  assert.equal(kb.vector_store_id, null)
  assert.deepEqual(kb.indexing_strategy, { vector_enabled: true, keyword_enabled: true, graph_enabled: false, wiki_enabled: false })
  assert.equal(kb.chunking_config.chunk_size, 500)
  assert.deepEqual(kb.faq_config, { index_mode: 'x' })
  assert.equal(kb.knowledge_count, 3)
})

test('create payload maps strategy, chunking and later-stage blocks', () => {
  const body = toNexusBaseInput({
    name: 'n', type: 'document', embedding_model_id: 'm',
    chunking_config: { chunk_size: 600, chunk_overlap: 60, separators: ['\n'] },
    indexing_strategy: { vector_enabled: true, keyword_enabled: false, graph_enabled: false, wiki_enabled: false },
    faq_config: { index_mode: 'question_only' },
  })
  assert.deepEqual(body.indexing_strategy, { vector: true, keyword: false, graph: false, wiki: false })
  assert.deepEqual(body.chunking_config, { chunk_size: 600, chunk_overlap: 60 })
  assert.deepEqual(body.settings, { faq_config: { index_mode: 'question_only' }, chunking_config: { separators: ['\n'] } })
  const update = toNexusBaseInput({ name: 'n2', config: { indexing_strategy: { vector_enabled: false, keyword_enabled: true } } })
  assert.equal(update.name, 'n2')
  assert.deepEqual(update.indexing_strategy, { vector: false, keyword: true, graph: false, wiki: false })
})

test('documents, chunks and hits map to WeKnora rows', () => {
  const doc = { id: 'd', kb_id: 'k', filename: 'a.md', file_type: 'md',
    latest_version: { state: 'failed', error_code: 'empty_text', size: 5, version: 2 },
    current_version: { chunk_count: 4, updated_at: 't' } }
  const row = toWeKnoraKnowledge(doc, '库')
  assert.equal(row.parse_status, 'failed')
  assert.equal(row.error_message, 'empty_text')
  assert.equal(row.chunk_count, 4)
  assert.equal(parseStatus({ latest_version: { state: 'embedded' } }), 'processing')
  assert.equal(parseStatus({ latest_version: { state: 'ready' } }), 'completed')
  assert.equal(toWeKnoraChunk({ id: 'c', ordinal: 3, content: 'x', page: 2, section: ['A'] }, 'd').chunk_index, 3)
  const hit = toWeKnoraSearchHit({ chunk_id: 'c', channels: { vector: 1, keyword: 2 }, filename: 'a.md' })
  assert.equal(hit.match_type, 'hybrid')
})

test('paging and planned errors', () => {
  assert.deepEqual(pageToOffset(3, 25), { offset: 50, limit: 25 })
  const error = new PlannedFeatureError('FAQ', 'K3')
  assert.equal(isPlannedFeatureError(error), true)
  assert.match(error.message, /K3/)
})

test('FAQ entries map both ways and imports report blocked rows', () => {
  const entry = toWeKnoraFaqEntry({ id: 'e1', kb_id: 'k', standard_question: 'q', answers: ['a'], category: '账号', is_enabled: false })
  assert.equal(entry.id, 'e1')
  assert.equal(entry.is_enabled, false)
  assert.equal(entry.tag_name, '账号')
  const body = toNexusFaqInput({ standard_question: 'q', answers: ['a'], tag_name: '账号', is_enabled: false })
  assert.deepEqual([body.category, body.is_enabled, body.answer_strategy], ['账号', false, 'all'])
  const progress = toFaqImportProgress('t', 'k', 3, { created: 2, blocked: [{ index: 1, standard_question: 'q', reason: '重复' }], notes: [] })
  assert.deepEqual([progress.status, progress.blocked, progress.total], ['completed', 1, 3])
})
