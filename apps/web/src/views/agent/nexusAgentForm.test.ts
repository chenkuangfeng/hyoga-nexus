import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { NexusAgent } from '../../api/nexus-agents.ts'
import { draftFromForm, formForNewAgent, formFromAgent, validateForm } from './nexusAgentForm.ts'

const TENANT = 't-1'

function agent(overrides: Partial<NexusAgent> = {}): NexusAgent {
  return {
    id: 'a-1', tenant_id: TENANT, name: 'Helper', description: 'd', status: 'published',
    published_version_id: 'v-1', version_counter: 1, runtime_type: 'native', instructions: 'Be precise',
    model_profile_version_id: 'm-1',
    budgets: { max_rounds: 8, max_tokens: 9000, behavior: { project_name: 'x' }, generation: { temperature: 0.3, reasoning_effort: 'high' } },
    resource_bindings: [
      { kind: 'tool', resource_id: 'todo', resource_version_id: 'v1', source_tenant_id: TENANT, config: {} },
      { kind: 'skill', resource_id: 'report', resource_version_id: 's-1', source_tenant_id: TENANT, config: {} },
    ],
    created_at: '', updated_at: '', ...overrides,
  }
}

test('form reads generation, budgets and tool bindings from the agent', () => {
  const form = formFromAgent(agent())
  assert.equal(form.temperature, 0.3)
  assert.equal(form.reasoning_effort, 'high')
  assert.equal(form.max_iterations, 8)
  assert.equal(form.max_completion_tokens, 0)
  assert.equal(form.llm_call_timeout, null)
  assert.deepEqual(form.allowed_tools, ['todo'])
})

test('without agent temperature the form starts from the model profile option', () => {
  const form = formFromAgent(agent({ budgets: {} }), { temperature: 1.1 })
  assert.equal(form.temperature, 1.1)
  assert.equal(form.reasoning_effort, 'auto')
})

test('draft keeps other budgets and non-tool bindings, and replaces tools', () => {
  const form = { ...formFromAgent(agent()), allowed_tools: ['ask_user', 'ask_user'], reasoning_effort: 'auto' as const,
    max_completion_tokens: 4096, llm_call_timeout: 30 }
  const draft = draftFromForm(form, agent(), null, TENANT)
  assert.equal(draft.budgets.max_tokens, 9000)
  assert.deepEqual(draft.budgets.behavior, { project_name: 'x' })
  assert.equal(draft.budgets.max_output_tokens, 4096)
  assert.equal(draft.budgets.model_timeout_seconds, 30)
  assert.deepEqual(draft.budgets.generation, { temperature: 0.3 })
  assert.deepEqual(draft.resource_bindings.map(b => `${b.kind}:${b.resource_id}`), ['skill:report', 'tool:ask_user'])
})

test('default token and timeout remove the budget keys', () => {
  const base = agent({ budgets: { max_output_tokens: 1000, model_timeout_seconds: 10 } })
  const draft = draftFromForm({ ...formFromAgent(base), max_completion_tokens: 0, llm_call_timeout: null }, base, null, TENANT)
  assert.equal('max_output_tokens' in draft.budgets, false)
  assert.equal('model_timeout_seconds' in draft.budgets, false)
})

test('new agent starts from native defaults and default tools', () => {
  const defaults = { version: 1, settings: { budgets: { max_rounds: 20, max_tokens: 16000 }, behavior: { enabled_tools: ['todo'] } } }
  const form = formForNewAgent(defaults, 'm-9', ['todo'])
  assert.equal(form.max_iterations, 20)
  assert.deepEqual(form.allowed_tools, ['todo'])
  const draft = draftFromForm({ ...form, name: ' New ', system_prompt: 'x' }, null, defaults, TENANT)
  assert.equal(draft.name, 'New')
  assert.equal(draft.budgets.max_tokens, 16000)
  assert.deepEqual(draft.budgets.behavior, { enabled_tools: ['todo'] })
  assert.equal(draft.model_profile_version_id, 'm-9')
})

test('validation requires name, model and system prompt', () => {
  const errors = validateForm(formForNewAgent(null, '', []))
  assert.deepEqual(Object.keys(errors).sort(), ['model_id', 'name', 'system_prompt'])
})

test('memory switches are stored only when turned off and read back', () => {
  const inherited = formFromAgent(agent({ budgets: {} }))
  assert.equal(inherited.memory_enabled, true)
  assert.equal(inherited.memory_recall, true)
  assert.equal(draftFromForm(inherited, agent({ budgets: { memory: { enabled: false } } }), null, TENANT).budgets.memory, undefined)
  const off = draftFromForm({ ...inherited, memory_enabled: false, memory_recall: false }, agent({ budgets: {} }), null, TENANT)
  assert.deepEqual(off.budgets.memory, { enabled: false, recall: false })
  const read = formFromAgent(agent({ budgets: { memory: { recall: false } } }))
  assert.equal(read.memory_enabled, true)
  assert.equal(read.memory_recall, false)
})

test('tool access is read from behavior and written only when set', () => {
  assert.equal(formFromAgent(agent({ budgets: {} })).tool_access, 'standard')
  const strict = formFromAgent(agent({ budgets: { behavior: { tool_access: 'strict' } } }))
  assert.equal(strict.tool_access, 'strict')
  const draft = draftFromForm({ ...strict, tool_access: 'read_only' }, agent({ budgets: { behavior: { tool_access: 'strict', x: 1 } } }), null, TENANT)
  assert.deepEqual(draft.budgets.behavior, { tool_access: 'read_only', x: 1 })
  assert.equal(draftFromForm(formFromAgent(agent({ budgets: {} })), agent({ budgets: {} }), null, TENANT).budgets.behavior, undefined)
})

test('knowledge bases are bound together with the required search tool', () => {
  const base = agent()
  const form = { ...formFromAgent(base), knowledge_bases: [{ id: 'kb-1', source_tenant_id: TENANT }] }
  const draft = draftFromForm(form, base, null, TENANT)
  const ids = draft.resource_bindings.map(b => `${b.kind}:${b.resource_id}`)
  assert.deepEqual(ids.filter(id => id.startsWith('knowledge_base')), ['knowledge_base:kb-1'])
  assert.ok(ids.includes('tool:search_knowledge'))
  assert.equal(ids.includes('tool:read_document'), false)  // optional tools are bound only when the editor selected them
  const back = formFromAgent({ ...base, resource_bindings: draft.resource_bindings as never })
  assert.deepEqual(back.knowledge_bases, [{ id: 'kb-1', source_tenant_id: TENANT }])
  const cleared = draftFromForm({ ...back, knowledge_bases: [] }, { ...base, resource_bindings: draft.resource_bindings as never }, null, TENANT)
  assert.equal(cleared.resource_bindings.some(b => b.kind === 'knowledge_base'), false)
})
