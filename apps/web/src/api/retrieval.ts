import { PlannedFeatureError } from './knowledge-base/nexusAdapter'

// RetrievalConfig represents the global retrieval/search configuration for a tenant.
// Shared by knowledge search and message search.
export interface RetrievalConfig {
  embedding_top_k: number
  vector_threshold: number
  keyword_threshold: number
  rerank_top_k: number
  rerank_threshold: number
  rerank_model_id: string
  rrf_k?: number
  rrf_vector_weight?: number
  rrf_keyword_weight?: number
}

// Space-level retrieval tuning (thresholds, rerank) is planned (openspec 2026-11-06-knowledge-base K5).
// Nexus currently fuses keyword and vector results with weighted RRF (k=60, weights 1:1); the page shows
// these values read-only.
export const NEXUS_RETRIEVAL_DEFAULTS: RetrievalConfig = {
  embedding_top_k: 30, vector_threshold: 0, keyword_threshold: 0, rerank_top_k: 0, rerank_threshold: 0,
  rerank_model_id: '', rrf_k: 60, rrf_vector_weight: 1, rrf_keyword_weight: 1,
}

export function getTenantRetrievalConfig() {
  return Promise.resolve({ success: true, data: { ...NEXUS_RETRIEVAL_DEFAULTS } })
}

export function updateTenantRetrievalConfig(config: RetrievalConfig) {
  void config
  return Promise.reject(new PlannedFeatureError('检索参数设置', 'K5'))
}
