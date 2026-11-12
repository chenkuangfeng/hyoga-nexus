import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { ModelSettingsView } from '@nexus-web/core/api/nexus-models'
import {
  chatModelOptions, countByType, defaultChatVersion, filterCards, flattenModelCards, manageableProviders,
  modelOptionsFor, planSave, type ModelEditorForm,
} from './nexusModelCards.ts'

const view: ModelSettingsView = {
  providers: [
    { id: 'p1', name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', scope: 'tenant', key_configured: true, key_mask: '•', models: [
      { id: 'm1', name: 'deepseek-chat', model_type: 'chat', version_id: 'v1', version: 1, options: { temperature: 0.5 } },
      { id: 'm2', name: 'bge-m3', model_type: 'embedding', version_id: 'v2', version: 1, options: {} },
    ] },
    { id: 'p2', name: 'Mine', base_url: 'https://example.com/v1', scope: 'personal', key_configured: true, key_mask: '•', models: [
      { id: 'm3', name: 'gpt-x', model_type: 'chat', version_id: 'v3', version: 2, options: {} },
    ] },
  ],
  defaults: { personal: { chat: 'v3' }, tenant: { chat: 'v1' } },
  can_manage_tenant: false,
}

const form: ModelEditorForm = {
  model_type: 'chat', model_name: 'x', provider_id: '', provider_name: 'New', base_url: 'https://n.example/v1',
  api_key: 'sk', scope: 'personal', protocol: 'openai_chat_completions',
}

test('cards flatten providers, mark defaults and management rights', () => {
  const cards = flattenModelCards(view)
  assert.equal(cards.length, 3)
  assert.deepEqual(cards.find(c => c.model.id === 'm1')!.defaultScopes, ['tenant'])
  assert.deepEqual(cards.find(c => c.model.id === 'm3')!.defaultScopes, ['personal'])
  assert.equal(cards.find(c => c.model.id === 'm1')!.canManage, false)
  assert.equal(cards.find(c => c.model.id === 'm3')!.canManage, true)
  assert.deepEqual(countByType(cards), { all: 3, chat: 2, embedding: 1, rerank: 0, vision: 0, speech: 0 })
  assert.deepEqual(filterCards(cards, 'chat', 'deep').map(c => c.model.id), ['m1'])
  assert.deepEqual(manageableProviders(view).map(p => p.id), ['p2'])
})

test('agent model options list chat models only; personal default wins', () => {
  assert.deepEqual(chatModelOptions(view).map(o => o.value), ['v1', 'v3'])
  assert.equal(defaultChatVersion(view), 'v3')
  assert.equal(defaultChatVersion({ ...view, defaults: { tenant: { chat: 'v1' } } }), 'v1')
})

test('save plan creates a provider once and reuses it on retry', () => {
  assert.deepEqual(planSave(form, null), { kind: 'create-provider-then-add' })
  assert.deepEqual(planSave(form, null, 'p9'), { kind: 'add', providerId: 'p9' })
  assert.deepEqual(planSave({ ...form, provider_id: 'p2' }, null), { kind: 'add', providerId: 'p2' })
})

test('editing updates the provider only when its fields change', () => {
  const card = flattenModelCards(view).find(c => c.model.id === 'm3')!
  const same = { ...form, provider_name: 'Mine', base_url: 'https://example.com/v1', api_key: '' }
  assert.deepEqual(planSave(same, card), { kind: 'edit', providerId: 'p2', profileId: 'm3', updateProvider: false })
  assert.equal((planSave({ ...same, api_key: 'new' }, card) as { updateProvider: boolean }).updateProvider, true)
})

test('non-chat models send no options; chat keeps known options', () => {
  assert.deepEqual(modelOptionsFor({ ...form, model_type: 'embedding' }, { temperature: 1 }), {})
  assert.deepEqual(modelOptionsFor(form, { temperature: 0.5, base_url: 'x' }), { temperature: 0.5, protocol: 'openai_chat_completions' })
})
