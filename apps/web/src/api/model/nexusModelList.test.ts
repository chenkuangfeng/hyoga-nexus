import assert from 'node:assert/strict'
import { test } from 'node:test'

import { modelsFromSettings } from './nexusModelList.ts'

test('Nexus models become WeKnora model configs keyed by version id', () => {
  const rows = modelsFromSettings({
    providers: [{ id: 'p', name: 'OpenAI', base_url: 'https://x/v1', scope: 'personal', key_configured: true, key_mask: '',
      models: [
        { id: 'm1', name: 'text-embedding-3', model_type: 'embedding', version_id: 'v-e', version: 1, options: {} },
        { id: 'm2', name: 'gpt', model_type: 'chat', version_id: 'v-c', version: 2, options: {} },
      ] }],
    defaults: { personal: { embedding: 'v-e' } }, can_manage_tenant: false,
  } as never)
  assert.deepEqual(rows.map(row => [row.id, row.type, row.is_default]), [['v-e', 'Embedding', true], ['v-c', 'KnowledgeQA', false]])
})
