import type { ModelType } from '../types/modelSettings'

/**
 * Static starting list for the model editor. Choosing a preset only fills the model name; nothing is
 * stored from this list and the supplier's own model list remains authoritative. Names are common,
 * publicly documented identifiers; a space can enter any name the supplier accepts.
 */
export interface ModelPreset { type: ModelType; name: string; vision?: boolean }

export const MODEL_PRESETS: ModelPreset[] = [
  { type: 'chat', name: 'gpt-4o', vision: true },
  { type: 'chat', name: 'gpt-4o-mini' },
  { type: 'vision', name: 'gpt-4o', vision: true },
  { type: 'embedding', name: 'text-embedding-3-small' },
  { type: 'embedding', name: 'text-embedding-3-large' },
  { type: 'rerank', name: 'bge-reranker-v2-m3' },
  { type: 'speech', name: 'whisper-1' },
]

/** Presets for one capability type, in list order. */
export function presetsFor(type: ModelType): ModelPreset[] {
  return MODEL_PRESETS.filter(preset => preset.type === type)
}
