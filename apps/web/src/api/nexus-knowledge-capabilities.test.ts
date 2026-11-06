import assert from 'node:assert/strict'
import { test } from 'node:test'

import { capabilityState, catalogFromResponse, emptyCatalog, groupItems, isAvailable } from './nexus-knowledge-capabilities.ts'

const catalog = catalogFromResponse({
  groups: ['kb_type', 'vector_engine'],
  items: [
    { group: 'kb_type', key: 'document', label: '文档库', stage: 'K1', status: 'available', verified: true },
    { group: 'kb_type', key: 'faq', label: 'FAQ 库', stage: 'K3', status: 'planned', verified: false },
    { group: 'vector_engine', key: 'qdrant', label: 'Qdrant', stage: 'K1', status: 'available', verified: false },
    { group: 'vector_engine', key: 'weaviate', label: 'Weaviate', stage: null, status: 'planned', verified: false },
    { key: 'no-group' },
  ],
})

test('catalog parsing drops malformed items and indexes by group/key', () => {
  assert.equal(catalog.items.length, 4)
  assert.equal(groupItems(catalog, 'vector_engine').map(item => item.key).join(','), 'qdrant,weaviate')
  assert.throws(() => catalogFromResponse({}))
})

test('availability and badges follow the backend status', () => {
  assert.equal(isAvailable(catalog, 'kb_type', 'document'), true)
  assert.equal(isAvailable(catalog, 'kb_type', 'faq'), false)
  assert.deepEqual(capabilityState(catalog, 'kb_type', 'document'), { kind: 'available' })
  assert.deepEqual(capabilityState(catalog, 'kb_type', 'faq'), { kind: 'planned', stage: 'K3' })
  assert.deepEqual(capabilityState(catalog, 'vector_engine', 'weaviate'), { kind: 'planned', stage: null })
  assert.deepEqual(capabilityState(catalog, 'vector_engine', 'qdrant'), { kind: 'unverified' })
})

test('unknown keys and the empty catalog fail closed', () => {
  assert.equal(isAvailable(catalog, 'kb_type', 'unknown'), false)
  assert.equal(isAvailable(emptyCatalog(), 'kb_type', 'document'), false)
  assert.deepEqual(capabilityState(emptyCatalog(), 'kb_type', 'document'), { kind: 'planned', stage: null })
})
