/**
 * Model list for the copied WeKnora pages, built from the Nexus model settings
 * (openspec 2026-11-06-knowledge-base K1.9).
 *
 * WeKnora pages (knowledge base editor, chat input) read `ModelConfig[]` with `type` names such as
 * `Embedding`. Nexus keeps providers with models; a model's *version id* is what agents and knowledge bases
 * reference, so it becomes `ModelConfig.id`. Pure mapping, unit tested.
 */
import type { ModelSettingsView, NexusModelType } from '../nexus-models'

const TYPE_MAP: Record<NexusModelType, string> = {
  chat: 'KnowledgeQA', embedding: 'Embedding', rerank: 'Rerank', vision: 'VLLM', speech: 'ASR',
}

export function modelsFromSettings(view: ModelSettingsView): Array<Record<string, any>> {
  const out: Array<Record<string, any>> = []
  for (const provider of view.providers) {
    for (const model of provider.models) {
      out.push({
        id: model.version_id, name: model.name, display_name: model.display_name || model.name,
        type: TYPE_MAP[model.model_type] ?? 'KnowledgeQA', source: 'remote',
        description: provider.name, parameters: { base_url: provider.base_url, provider: provider.name },
        is_default: Object.values(view.defaults).some(scope => Object.values(scope || {}).includes(model.version_id)),
      })
    }
  }
  return out
}
