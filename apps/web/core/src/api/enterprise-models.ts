/** 企业模型管理客户端：显式企业路径、租户 Provider 过滤和真实 DTO 校验。 */
import { del, get, post, put } from '../utils/request'

export type EnterpriseModelType = 'chat' | 'embedding' | 'rerank' | 'vision' | 'speech'
export type EnterpriseModelProtocol = 'openai_chat_completions' | 'openai_responses' | 'anthropic_messages'
export interface EnterpriseModelProfile {
  id: string; name: string; model_type: EnterpriseModelType; version_id: string; version: number
  options: Record<string, unknown>
}
export interface EnterpriseModelProvider {
  id: string; name: string; base_url: string; scope: 'tenant'; key_configured: boolean; key_mask: string
  models: EnterpriseModelProfile[]
}
interface ModelProviderResponse extends Omit<EnterpriseModelProvider, 'scope'> { scope: 'tenant' | 'personal' }
export interface EnterpriseModelSettings {
  providers: EnterpriseModelProvider[]
  defaults: Partial<Record<EnterpriseModelType, string>>
  can_manage_tenant: boolean
}
export interface EnterpriseProviderInput { name: string; base_url: string; scope: 'tenant'; api_key?: string }
export interface EnterpriseModelInput { name: string; model_type: EnterpriseModelType; options: Record<string, unknown> }
export interface EnterpriseModelConnectionResult { ok: boolean; message: string; code?: string }

const types: EnterpriseModelType[] = ['chat', 'embedding', 'rerank', 'vision', 'speech']
const protocols: EnterpriseModelProtocol[] = ['openai_chat_completions', 'openai_responses', 'anthropic_messages']
const invalid = () => new Error('enterprise_model_response_invalid')
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(); return value as Record<string, unknown> }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw invalid(); return value }
function string(value: unknown): string { if (typeof value !== 'string') throw invalid(); return value }
function positiveInt(value: unknown): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) throw invalid(); return value }
function modelType(value: unknown): EnterpriseModelType { if (typeof value !== 'string' || !types.includes(value as EnterpriseModelType)) throw invalid(); return value as EnterpriseModelType }
function modelFromResponse(value: unknown): EnterpriseModelProfile {
  const row = object(value)
  return { id: string(row.id), name: string(row.name), model_type: modelType(row.model_type), version_id: string(row.version_id),
    version: positiveInt(row.version), options: object(row.options) }
}
function providerFromResponse(value: unknown): ModelProviderResponse {
  const row = object(value)
  if (row.scope !== 'tenant' && row.scope !== 'personal') throw invalid()
  if (typeof row.key_configured !== 'boolean' || (row.scope === 'tenant' && row.key_configured !== true)) throw invalid()
  const models = array(row.models).map(modelFromResponse)
  if (new Set(models.map(model => model.id)).size !== models.length || new Set(models.map(model => model.version_id)).size !== models.length) throw invalid()
  return { id: string(row.id), name: string(row.name), base_url: string(row.base_url), scope: row.scope,
    key_configured: row.key_configured, key_mask: string(row.key_mask), models }
}
const root = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}/admin/model-settings`

/** Load settings for the selected enterprise and omit all personal-provider records. */
export async function listEnterpriseModelSettings(tenant: string): Promise<EnterpriseModelSettings> {
  const row = object(await get(root(tenant))), providers = array(row.providers).map(providerFromResponse)
  if (typeof row.can_manage_tenant !== 'boolean') throw invalid()
  const rawDefaults = object(row.defaults), tenantDefaults = rawDefaults.tenant === undefined ? {} : object(rawDefaults.tenant)
  const defaults: Partial<Record<EnterpriseModelType, string>> = {}
  for (const [key, value] of Object.entries(tenantDefaults)) {
    if (!types.includes(key as EnterpriseModelType)) throw invalid()
    defaults[key as EnterpriseModelType] = string(value)
  }
  const tenantProviders = providers.filter((provider): provider is ModelProviderResponse & { scope: 'tenant' } => provider.scope === 'tenant')
  if (new Set(tenantProviders.map(provider => provider.id)).size !== tenantProviders.length) throw invalid()
  return { providers: tenantProviders, defaults, can_manage_tenant: row.can_manage_tenant }
}

/** Create or update a shared provider; API keys are write-only and never returned. */
export async function saveEnterpriseModelProvider(tenant: string, input: EnterpriseProviderInput, id?: string): Promise<void> {
  const url = id ? `${root(tenant)}/providers/${encodeURIComponent(id)}` : `${root(tenant)}/providers`
  const result = object(id ? await put(url, input) : await post(url, input))
  const provider = providerFromResponse(result)
  if (provider.scope !== 'tenant' || (id && provider.id !== id)) throw invalid()
}

/** Add a model or append an immutable version to an existing model profile. */
export async function saveEnterpriseModel(tenant: string, providerId: string, input: EnterpriseModelInput, profileId?: string): Promise<void> {
  const url = profileId
    ? `${root(tenant)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}`
    : `${root(tenant)}/providers/${encodeURIComponent(providerId)}/models`
  const result = object(profileId ? await put(url, input) : await post(url, input)), id = string(result.id)
  if (!id || (profileId && id !== profileId) || !string(result.version_id)) throw invalid()
}

/** Disable a tenant provider and revoke its credentials; history remains on the server. */
export async function disableEnterpriseModelProvider(tenant: string, providerId: string): Promise<void> {
  const result = object(await del(`${root(tenant)}/providers/${encodeURIComponent(providerId)}`))
  if (string(result.status) !== 'disabled') throw invalid()
}

/** Disable a model profile and clear defaults without deleting historical versions. */
export async function disableEnterpriseModel(tenant: string, providerId: string, profileId: string): Promise<void> {
  const result = object(await del(`${root(tenant)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}`))
  if (string(result.status) !== 'disabled') throw invalid()
}

/** Set or clear one enterprise default; the backend checks type and current-version ownership. */
export async function setEnterpriseModelDefault(tenant: string, modelTypeValue: EnterpriseModelType, versionId: string | null): Promise<void> {
  const result = object(await put(`${root(tenant)}/default`, { scope: 'tenant', model_type: modelTypeValue, version_id: versionId }))
  if (string(result.status) !== 'saved') throw invalid()
}

/** Run the backend's bounded, sanitized connection check for one saved model. */
export async function testEnterpriseModel(tenant: string, providerId: string, profileId: string): Promise<EnterpriseModelConnectionResult> {
  const row = object(await post(`${root(tenant)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}/test`, {}))
  if (typeof row.ok !== 'boolean') throw invalid()
  const result: EnterpriseModelConnectionResult = { ok: row.ok, message: string(row.message) }
  if (row.code !== undefined) result.code = string(row.code)
  return result
}

export function enterpriseModelProtocol(value: unknown): EnterpriseModelProtocol {
  if (value === undefined) return 'openai_chat_completions'
  if (typeof value !== 'string' || !protocols.includes(value as EnterpriseModelProtocol)) throw invalid()
  return value as EnterpriseModelProtocol
}
