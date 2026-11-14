import type { ModelConfig } from '@nexus-web/core/api/model/index'

export type ModelSelectorType = ModelConfig['type']

export function filterModelsByType(
  allModels: ModelConfig[],
  modelType: ModelSelectorType,
): ModelConfig[] {
  if (modelType === 'VLLM') {
    return allModels.filter(
      (m) =>
        m.type === 'VLLM' ||
        (m.type === 'KnowledgeQA' && m.parameters?.supports_vision === true),
    )
  }

  return allModels.filter((m) => m.type === modelType)
}
