export type SettingsScope = 'personal' | 'tenant'

/** Capability types a configured model can declare; mirrors the backend `MODEL_TYPES`. */
export const MODEL_TYPES = ['chat', 'embedding', 'rerank', 'vision', 'speech'] as const
export type ModelType = typeof MODEL_TYPES[number]

export interface ConfiguredModel { id: string; name: string; model_type: ModelType; version_id: string; version: number; options?: Record<string, unknown> }
export interface ModelProvider { id: string; name: string; base_url: string; scope: SettingsScope; key_configured: boolean; models: ConfiguredModel[] }
/** Default model version per scope and type; a missing slot means "not set". */
export type ModelDefaults = Partial<Record<SettingsScope, Partial<Record<ModelType, string>>>>
export interface ModelSettings { providers: ModelProvider[]; defaults: ModelDefaults; can_manage_tenant: boolean }
export interface ProviderInput { name: string; base_url: string; scope: SettingsScope; api_key?: string }
/** Connection test for an unsaved configuration. `provider_id` reuses that provider's stored Key when `api_key` is omitted. */
export interface DraftTestInput { scope: SettingsScope; base_url: string; model_name: string; model_type: ModelType; options: Record<string, unknown>; provider_id?: string; api_key?: string }
export interface TestResult { ok: boolean; message: string; code?: string }
