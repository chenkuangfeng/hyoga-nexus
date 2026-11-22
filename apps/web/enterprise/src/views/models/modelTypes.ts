import type { EnterpriseModelProfile, EnterpriseModelProvider, EnterpriseModelType } from '@nexus-web/core/api/enterprise-models'

export const modelTypes: EnterpriseModelType[] = ['chat', 'embedding', 'rerank', 'vision', 'speech']
export const modelTypeIcons: Record<EnterpriseModelType, string> = {
  chat: 'chat', embedding: 'chart-bubble', rerank: 'filter-sort', vision: 'image', speech: 'sound',
}

export interface ModelCard {
  provider: EnterpriseModelProvider
  model: EnterpriseModelProfile
}

export function modelLabel(model: EnterpriseModelProfile): string {
  return model.display_name || model.name
}
