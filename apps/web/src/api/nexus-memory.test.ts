import assert from 'node:assert/strict'
import { test } from 'node:test'

import { memoryListFromResponse } from './nexus-memory-types.ts'

test('memory list keeps metadata, hints and merge targets and drops malformed items', () => {
  const listed = memoryListFromResponse({
    entries: [{ id: 'e1', title: '构建', kind: 'memory', project: '', version: 2, enabled: true, valid_until: null,
      topic: '构建', importance: 4 }, { title: 'no id' }],
    drafts: [{
      id: 'd1', kind: 'memory', diff: '改用 bazel', origin: 'background', base_version: 2, target_entry_id: 'e1',
      topic: '构建', importance: 4, confidence: 'high', valid_until: null,
      evidence: [{ message_id: 'm1', sequence: 3, quote: '改用 bazel' }, { quote: '' }],
      annotations: { conflict: [{ entry_id: 'e9', title: '旧' }], similar: [{ entry_id: 'e8', title: '近', score: 0.7 }],
        merge: { archive: [{ id: 'e2', title: '另一条', version: 1 }] } },
    }, 'bad'],
  })
  assert.equal(listed.entries.length, 1)
  assert.equal(listed.entries[0].importance, 4)
  const [draft] = listed.drafts
  assert.deepEqual(draft.evidence, [{ quote: '改用 bazel', sequence: 3, message_id: 'm1' }])
  assert.deepEqual(draft.conflicts, [{ entry_id: 'e9', title: '旧' }])
  assert.deepEqual(draft.similar, [{ entry_id: 'e8', title: '近', score: 0.7 }])
  assert.deepEqual(draft.merges, [{ id: 'e2', title: '另一条', version: 1 }])
  assert.equal(draft.target_entry_id, 'e1')
})

test('a response without the two lists is rejected', () => {
  assert.throws(() => memoryListFromResponse({ entries: [] }))
})
