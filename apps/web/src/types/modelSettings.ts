export type SettingsScope = 'personal' | 'tenant'
export interface ConfiguredModel { id: string; name: string; version_id: string; version: number; options?: Record<string, unknown> }
export interface ModelProvider { id: string; name: string; base_url: string; scope: SettingsScope; key_configured: boolean; models: ConfiguredModel[] }
export interface ModelSettings { providers: ModelProvider[]; defaults: Partial<Record<SettingsScope, string>>; can_manage_tenant: boolean }
export interface ProviderInput { name: string; base_url: string; scope: SettingsScope; api_key?: string }
