import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { NexusAgent } from '../../api/nexus-agents.ts'
import { SKILL_BASE_TOOLS, draftFromForm, formForNewAgent, formFromAgent, skillHasNewerVersion, skillToolNeeds, validateForm } from './nexusAgentForm.ts'

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

test('bound skills are read from the agent and written back with their own space and version', () => {
  const builtin = { kind: 'skill', resource_id: 'weekly-report', resource_version_id: 'v-9', source_tenant_id: 'system', config: {} }
  const form = formFromAgent(agent({ resource_bindings: [...agent().resource_bindings, builtin] }))
  assert.deepEqual(form.skills, [
    { name: 'report', version_id: 's-1', source_tenant_id: TENANT },
    { name: 'weekly-report', version_id: 'v-9', source_tenant_id: 'system' },
  ])
  const draft = draftFromForm(form, agent(), null, TENANT)
  const skills = draft.resource_bindings.filter(b => b.kind === 'skill')
  assert.deepEqual(skills.map(b => [b.resource_id, b.resource_version_id, b.source_tenant_id]),
    [['report', 's-1', TENANT], ['weekly-report', 'v-9', 'system']])
})

test('clearing the skills removes their bindings, and a new agent has none', () => {
  const form = { ...formFromAgent(agent()), skills: [] }
  assert.equal(draftFromForm(form, agent(), null, TENANT).resource_bindings.some(b => b.kind === 'skill'), false)
  assert.deepEqual(formForNewAgent(null, 'm-1', []).skills, [])
})

test('the sandbox profile is stored only when chosen, and the default leaves no key behind', () => {
  assert.equal(formForNewAgent(null, 'm-1', []).sandbox_profile, '')
  const chosen = { ...formFromAgent(agent()), sandbox_profile: 'strict' }
  assert.equal((draftFromForm(chosen, agent(), null, TENANT).budgets.behavior as Record<string, unknown>).sandbox_profile, 'strict')
  const stored = agent({ budgets: { behavior: { sandbox_profile: 'strict', project_name: 'x' } } })
  const form = formFromAgent(stored)
  assert.equal(form.sandbox_profile, 'strict')
  const back = draftFromForm({ ...form, sandbox_profile: '' }, stored, null, TENANT)
  assert.deepEqual(back.budgets.behavior, { project_name: 'x' })  // other behavior keys are kept
  assert.equal('behavior' in draftFromForm({ ...formFromAgent(agent({ budgets: {} })), sandbox_profile: '' }, agent({ budgets: {} }), null, TENANT).budgets, false)
})

test('a skill needs the skill readers and the tools it declares; missing ones are named', () => {
  const offered = new Set(['load_skill', 'read_skill_file', 'read_memory'])
  assert.deepEqual(skillToolNeeds([], offered), { needed: [...SKILL_BASE_TOOLS], missing: [] })
  assert.deepEqual(skillToolNeeds(['read_memory', 'search_memory', 'load_skill'], offered),
    { needed: ['load_skill', 'read_skill_file', 'read_memory', 'search_memory'], missing: ['search_memory'] })
  assert.deepEqual(skillToolNeeds([], new Set()).missing, ['load_skill', 'read_skill_file'])
})

test('a newer version is reported only for a bound skill with a known latest version', () => {
  const bound = { name: 'a', version_id: 'v1', source_tenant_id: 's' }
  assert.equal(skillHasNewerVersion(bound, 'v2'), true)
  assert.equal(skillHasNewerVersion(bound, 'v1'), false)
  assert.equal(skillHasNewerVersion(undefined, 'v2'), false)
  assert.equal(skillHasNewerVersion(bound, null), false)
  assert.equal(skillHasNewerVersion({ ...bound, version_id: '' }, 'v2'), false)
})

test('tool group switches round-trip, keep other behavior keys, and are dropped when none remain', () => {
  const stored = agent({ budgets: { behavior: { tool_groups_enabled: { sandbox: true, web: 'x' }, project_name: 'x' } } })
  const form = formFromAgent(stored)
  assert.deepEqual(form.tool_groups_enabled, { sandbox: true })
  const kept = draftFromForm({ ...form, tool_groups_enabled: { sandbox: true, mcp: true } }, stored, null, TENANT)
  assert.deepEqual((kept.budgets.behavior as Record<string, unknown>).tool_groups_enabled, { sandbox: true, mcp: true })
  assert.equal((kept.budgets.behavior as Record<string, unknown>).project_name, 'x')
  const cleared = draftFromForm({ ...form, tool_groups_enabled: {} }, stored, null, TENANT)
  assert.equal('tool_groups_enabled' in (cleared.budgets.behavior as Record<string, unknown>), false)
  assert.deepEqual(formForNewAgent(null, 'm-1', []).tool_groups_enabled, {})
})
