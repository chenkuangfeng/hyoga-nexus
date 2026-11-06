/**
 * Mapping between the agent editor form (WeKnora `CustomAgentConfig` fields) and the Nexus
 * `AgentDraftInput` (openspec 2026-11-05-weknora-agent-tool-model-settings, design.md section 2).
 *
 * Pure functions with no Vue or network dependency, so they are unit tested directly.
 * Type-only imports keep this module loadable by `tsx --test` without the HTTP client.
 */
import type { AgentDraftInput, AgentResourceBinding, NativeDefaults, NexusAgent } from '../../api/nexus-agents'

/** `ExecutionBudget` defaults in `nexus_core.runtime.budgets`; shown when the agent sets no value. */
export const DEFAULT_MAX_OUTPUT_TOKENS = 2048
export const DEFAULT_MAX_ROUNDS = 12
export const DEFAULT_MODEL_TIMEOUT_SECONDS = 60
/** Service limits enforced by `runs/settings.py` and the worker. */
export const MAX_OUTPUT_TOKENS_LIMIT = 128000
export const MAX_ROUNDS_LIMIT = 1000
export const DEFAULT_TEMPERATURE = 0.7

/** Reasoning levels accepted in `budgets.generation.reasoning_effort`; `auto` follows the model profile. */
export const REASONING_EFFORTS = ['off', 'auto', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'] as const
export type ReasoningEffort = (typeof REASONING_EFFORTS)[number]

export interface AgentEditorForm {
  name: string
  description: string
  system_prompt: string
  /** Model profile version id; empty until the user selects one. */
  model_id: string
  temperature: number
  reasoning_effort: ReasoningEffort
  /** 0 means "follow the default" (no `max_output_tokens` in budgets). */
  max_completion_tokens: number
  max_iterations: number
  /** Seconds; null means "follow the default". */
  llm_call_timeout: number | null
  allowed_tools: string[]
  /** Bound knowledge bases (openspec 2026-11-06-knowledge-base K1.9); `source_tenant_id` is the base's space. */
  knowledge_bases: KnowledgeBinding[]
  /** `budgets.memory.enabled`: false turns long-term memory off for this agent; true inherits. */
  memory_enabled: boolean
  /** `budgets.memory.recall`: false stops per-turn memory recall (openspec 2026-11-06-memory-evolution D3). */
  memory_recall: boolean
  /** `budgets.behavior.tool_access` (openspec 2026-11-06-tool-call-hardening D11). */
  tool_access: ToolAccess
}

export interface KnowledgeBinding { id: string, source_tenant_id: string }

/** Knowledge tools bound together with the first knowledge base (publishing requires `search_knowledge`). */
export const KNOWLEDGE_TOOLS = ['search_knowledge', 'read_document', 'list_documents', 'query_knowledge_graph',
  'grep_chunks', 'document_outline'] as const

/** The one knowledge tool a published agent with knowledge bases must bind; the rest are optional extras. */
export const REQUIRED_KNOWLEDGE_TOOL = 'search_knowledge'

export const TOOL_ACCESS_LEVELS = ['read_only', 'standard', 'strict'] as const
export type ToolAccess = (typeof TOOL_ACCESS_LEVELS)[number]

function accessOf(budgets: Record<string, unknown> | undefined): ToolAccess {
  const behavior = budgets?.behavior
  const value = behavior && typeof behavior === 'object' ? (behavior as Record<string, unknown>).tool_access : undefined
  return (TOOL_ACCESS_LEVELS as readonly string[]).includes(value as string) ? (value as ToolAccess) : 'standard'
}

function memoryOf(budgets: Record<string, unknown> | undefined): Record<string, unknown> {
  const value = budgets?.memory
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function generationOf(budgets: Record<string, unknown> | undefined): Record<string, unknown> {
  const value = budgets?.generation
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function asEffort(value: unknown): ReasoningEffort {
  return (REASONING_EFFORTS as readonly string[]).includes(value as string) ? (value as ReasoningEffort) : 'auto'
}

/**
 * Build the form for an existing agent.
 *
 * `modelOptions` are the selected model profile's options: when the agent sets no temperature,
 * the form starts from the profile's value so saving does not silently change behaviour.
 */
export function formFromAgent(agent: NexusAgent, modelOptions: Record<string, unknown> = {}): AgentEditorForm {
  const budgets = agent.budgets || {}
  const generation = generationOf(budgets)
  return {
    name: agent.name,
    description: agent.description || '',
    system_prompt: agent.instructions || '',
    model_id: agent.model_profile_version_id || '',
    temperature: numberOr(generation.temperature, numberOr(modelOptions.temperature, DEFAULT_TEMPERATURE)),
    reasoning_effort: asEffort(generation.reasoning_effort),
    max_completion_tokens: typeof budgets.max_output_tokens === 'number' ? budgets.max_output_tokens : 0,
    max_iterations: numberOr(budgets.max_rounds, DEFAULT_MAX_ROUNDS),
    llm_call_timeout: typeof budgets.model_timeout_seconds === 'number' ? budgets.model_timeout_seconds : null,
    allowed_tools: (agent.resource_bindings || []).filter(b => b.kind === 'tool').map(b => b.resource_id),
    knowledge_bases: (agent.resource_bindings || []).filter(b => b.kind === 'knowledge_base')
      .map(b => ({ id: b.resource_id, source_tenant_id: b.source_tenant_id })),
    memory_enabled: memoryOf(budgets).enabled !== false,
    memory_recall: memoryOf(budgets).recall !== false,
    tool_access: accessOf(budgets),
  }
}

/** Initial form of a new agent: the caller's Native defaults and the preselected model. */
export function formForNewAgent(defaults: NativeDefaults | null, modelId: string, defaultTools: string[]): AgentEditorForm {
  const budgets = defaults?.settings.budgets || {}
  return {
    name: '',
    description: '',
    system_prompt: '',
    model_id: modelId,
    temperature: DEFAULT_TEMPERATURE,
    reasoning_effort: 'auto',
    max_completion_tokens: 0,
    max_iterations: numberOr(budgets.max_rounds, DEFAULT_MAX_ROUNDS),
    llm_call_timeout: null,
    allowed_tools: [...defaultTools],
    knowledge_bases: [],
    memory_enabled: true,
    memory_recall: true,
    tool_access: accessOf(defaults ? { behavior: defaults.settings.behavior } : undefined),
  }
}

/** Client-side checks mirroring the server; returns an i18n key per invalid field. */
export function validateForm(form: AgentEditorForm): Partial<Record<keyof AgentEditorForm, string>> {
  const errors: Partial<Record<keyof AgentEditorForm, string>> = {}
  if (!form.name.trim()) errors.name = 'agent.editor.nameRequired'
  if (!form.model_id) errors.model_id = 'agent.editor.modelRequired'
  if (!form.system_prompt.trim()) errors.system_prompt = 'agent.editor.systemPromptRequired'
  return errors
}

/**
 * Build the draft body.
 *
 * `base` is the agent being edited (null for a new agent); its other budget keys (for example the
 * Native `behavior` snapshot) and its non-tool bindings (for example skills bound elsewhere) are kept.
 * A new agent starts from the caller's Native defaults, like `POST model-settings/agents`.
 */
export function draftFromForm(form: AgentEditorForm, base: NexusAgent | null, defaults: NativeDefaults | null,
  tenantId: string): AgentDraftInput {
  const budgets: Record<string, unknown> = base
    ? { ...(base.budgets || {}) }
    : { ...(defaults?.settings.budgets || {}), ...(defaults ? { behavior: defaults.settings.behavior } : {}) }

  const tokens = Math.round(form.max_completion_tokens)
  if (tokens > 0) budgets.max_output_tokens = Math.min(tokens, MAX_OUTPUT_TOKENS_LIMIT)
  else delete budgets.max_output_tokens

  budgets.max_rounds = Math.min(Math.max(1, Math.round(form.max_iterations)), MAX_ROUNDS_LIMIT)

  if (form.llm_call_timeout !== null && form.llm_call_timeout > 0) budgets.model_timeout_seconds = form.llm_call_timeout
  else delete budgets.model_timeout_seconds

  const generation: Record<string, unknown> = { temperature: Math.min(Math.max(form.temperature, 0), 2) }
  if (form.reasoning_effort !== 'auto') generation.reasoning_effort = form.reasoning_effort
  budgets.generation = generation

  // Memory switches (openspec 2026-11-05-memory-switches, 2026-11-06-memory-evolution): only "off" is
  // stored; an agent that leaves both on inherits the space and member settings.
  const memory: Record<string, unknown> = {}
  if (!form.memory_enabled) memory.enabled = false
  if (!form.memory_recall) memory.recall = false
  if (Object.keys(memory).length) budgets.memory = memory
  else delete budgets.memory

  const behavior = budgets.behavior && typeof budgets.behavior === 'object' ? { ...(budgets.behavior as Record<string, unknown>) } : {}
  if (form.tool_access !== 'standard' || 'tool_access' in behavior) behavior.tool_access = form.tool_access
  if (Object.keys(behavior).length) budgets.behavior = behavior

  const kept = (base?.resource_bindings || []).filter(b => b.kind !== 'tool' && b.kind !== 'knowledge_base')
  // Binding a knowledge base needs search_knowledge (the server refuses to publish otherwise). The other knowledge
  // tools are chosen in the editor (only those the space has enabled are offered).
  const toolNames = form.knowledge_bases.length
    ? [...new Set([...form.allowed_tools, REQUIRED_KNOWLEDGE_TOOL])]
    : [...new Set(form.allowed_tools)]
  const tools: AgentDraftInput['resource_bindings'] = toolNames.map(name => ({
    kind: 'tool', resource_id: name, resource_version_id: 'v1', source_tenant_id: tenantId, config: {},
  }))
  const bases: AgentDraftInput['resource_bindings'] = form.knowledge_bases.map(kb => ({
    kind: 'knowledge_base', resource_id: kb.id, resource_version_id: '', source_tenant_id: kb.source_tenant_id, config: {},
  }))
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    runtime_type: 'native',
    instructions: form.system_prompt,
    model_profile_version_id: form.model_id,
    budgets,
    resource_bindings: [...kept.map((b: AgentResourceBinding) => ({ ...b })), ...tools, ...bases],
  }
}
