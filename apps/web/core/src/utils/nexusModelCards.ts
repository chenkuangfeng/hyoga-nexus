/**
 * Pure helpers for Settings → Models on Nexus (no Vue, no network; unit tested).
 *
 * WeKnora shows one card per model with its own address and Key. Nexus stores the address and
 * Key on a provider shared by its models, so each provider's models are flattened into cards that
 * carry the provider, and saving decides whether to reuse a provider or create one first.
 */
import type { ModelScope, ModelSettingsView, NexusModel, NexusModelType, NexusProvider } from '@nexus-web/core/api/nexus-models'

/** WeKnora model type ↔ Nexus model type. */
export const WEKNORA_TO_NEXUS_TYPE: Record<string, NexusModelType> = {
  KnowledgeQA: 'chat', Embedding: 'embedding', Rerank: 'rerank', VLLM: 'vision', ASR: 'speech',
}
export const NEXUS_TYPES: NexusModelType[] = ['chat', 'embedding', 'rerank', 'vision', 'speech']

export interface ModelCard {
  key: string
  provider: NexusProvider
  model: NexusModel
  type: NexusModelType
  defaultScopes: ModelScope[]
  /** Personal providers are managed by their owner; space providers need `can_manage_tenant`. */
  canManage: boolean
}

export function flattenModelCards(view: ModelSettingsView): ModelCard[] {
  const cards: ModelCard[] = []
  for (const provider of view.providers) {
    for (const model of provider.models) {
      const defaultScopes = (['personal', 'tenant'] as ModelScope[])
        .filter(scope => view.defaults[scope]?.[model.model_type] === model.version_id)
      cards.push({
        key: `${provider.id}:${model.id}`, provider, model, type: model.model_type, defaultScopes,
        canManage: provider.scope === 'personal' || view.can_manage_tenant,
      })
    }
  }
  return cards
}

export function countByType(cards: ModelCard[]): Record<NexusModelType | 'all', number> {
  const counts = { all: cards.length, chat: 0, embedding: 0, rerank: 0, vision: 0, speech: 0 }
  for (const card of cards) counts[card.type] += 1
  return counts
}

export function filterCards(cards: ModelCard[], type: NexusModelType | 'all', query: string): ModelCard[] {
  const needle = query.trim().toLowerCase()
  return cards.filter(card => (type === 'all' || card.type === type) && (!needle
    || card.model.name.toLowerCase().includes(needle) || card.provider.name.toLowerCase().includes(needle)))
}

/** Chat models usable by agents (only `chat` type; R5 "智能体的模型下拉只列出对话模型"). */
export function chatModelOptions(view: ModelSettingsView): Array<{ value: string; label: string; provider: string }> {
  return flattenModelCards(view).filter(card => card.type === 'chat')
    .map(card => ({ value: card.model.version_id, label: card.model.display_name || card.model.name, provider: card.provider.name }))
}

/** Personal default first, then space default (same order as `create_native_agent`). */
export function defaultChatVersion(view: ModelSettingsView): string {
  return view.defaults.personal?.chat || view.defaults.tenant?.chat || ''
}

export function findModelByVersion(view: ModelSettingsView, versionId: string): NexusModel | undefined {
  for (const provider of view.providers) {
    const model = provider.models.find(item => item.version_id === versionId)
    if (model) return model
  }
  return undefined
}

/** Editor form state; `provider_id = ''` means "custom provider" (create one on save). */
export interface ModelEditorForm {
  model_type: NexusModelType
  model_name: string
  provider_id: string
  provider_name: string
  base_url: string
  api_key: string
  scope: ModelScope
  protocol: string
}

export type SavePlan =
  | { kind: 'add'; providerId: string }
  | { kind: 'create-provider-then-add' }
  | { kind: 'edit'; providerId: string; profileId: string; updateProvider: boolean }

/**
 * Decide the calls for saving the form.
 *
 * `createdProviderId` is a provider this dialog already created in an earlier failed attempt; it is
 * reused so a retry never creates a second provider (R5). Editing changes the provider only when its
 * name, address or Key differ from the stored values.
 */
export function planSave(form: ModelEditorForm, editing: ModelCard | null, createdProviderId = ''): SavePlan {
  if (editing) {
    const provider = editing.provider
    const updateProvider = !!form.api_key || form.base_url.trim() !== provider.base_url
      || form.provider_name.trim() !== provider.name
    return { kind: 'edit', providerId: provider.id, profileId: editing.model.id, updateProvider }
  }
  if (form.provider_id) return { kind: 'add', providerId: form.provider_id }
  if (createdProviderId) return { kind: 'add', providerId: createdProviderId }
  return { kind: 'create-provider-then-add' }
}

/** Model options sent on save: non-chat types only send the default protocol (R5). */
export function modelOptionsFor(form: ModelEditorForm, previous: Record<string, unknown> = {}): Record<string, unknown> {
  if (form.model_type !== 'chat') return {}
  const options: Record<string, unknown> = {}
  for (const key of ['stream', 'temperature', 'reasoning_effort', 'text_tools']) {
    if (key in previous) options[key] = previous[key]
  }
  options.protocol = form.protocol || 'openai_chat_completions'
  return options
}

/** Providers the caller may attach a new model to, for the provider dropdown. */
export function manageableProviders(view: ModelSettingsView): NexusProvider[] {
  return view.providers.filter(provider => provider.scope === 'personal' || view.can_manage_tenant)
}
