// Chunker debug / preview API on the Nexus API (openspec 2026-11-06-knowledge-base K4): runs the chunker over
// a sample text without touching the database or embeddings. Used by the KB editor debug panel.

import { post } from '../../utils/request'
import { knowledgePath } from '../knowledge-base/nexusKnowledgeApi'
import type {
  PreviewChunkingRequest,
  PreviewChunkingResponse
} from '../../types/chunker'

export function previewChunking(
  body: PreviewChunkingRequest
): Promise<{ success: boolean; data: PreviewChunkingResponse }> {
  return post(`${knowledgePath()}/chunk-preview`, body)
}
