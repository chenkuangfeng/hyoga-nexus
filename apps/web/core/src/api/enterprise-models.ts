/** 企业模型管理客户端：显式企业路径、租户 Provider 过滤和真实 DTO 校验。 */
import { del, get, post, postUpload, put } from '../utils/request'

export type EnterpriseModelType = 'chat' | 'embedding' | 'rerank' | 'vision' | 'speech'
export type EnterpriseModelProtocol = 'openai_chat_completions' | 'openai_responses' | 'anthropic_messages'
export interface EnterpriseModelProfile {
  id: string; name: string; model_type: EnterpriseModelType; version_id: string; version: number
  display_name?: string
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
export type NewEnterpriseProvider = Pick<EnterpriseProviderInput, 'name' | 'base_url'> & { api_key: string }
export interface EnterpriseModelInput { name: string; display_name?: string; model_type: EnterpriseModelType; options: Record<string, unknown> }
export interface EnterpriseModelConnectionResult { ok: boolean; message: string; code?: string }
export interface EnterpriseModelDebugInput {
  text: string
  documents?: string[]
  system_prompt?: string
  max_output_tokens?: number
  temperature?: number
}
export type EnterpriseModelDebugResult =
  | { type: 'chat' | 'vision' | 'speech'; text: string }
  | { type: 'embedding'; dimension: number; preview: number[] }
  | { type: 'rerank'; scores: { index: number; score: number }[] }

const types: EnterpriseModelType[] = ['chat', 'embedding', 'rerank', 'vision', 'speech']
const protocols: EnterpriseModelProtocol[] = ['openai_chat_completions', 'openai_responses', 'anthropic_messages']
const invalid = () => new Error('enterprise_model_response_invalid')
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(); return value as Record<string, unknown> }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw invalid(); return value }
function string(value: unknown): string { if (typeof value !== 'string') throw invalid(); return value }
function positiveInt(value: unknown): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) throw invalid(); return value }
function finite(value: unknown): number { if (typeof value !== 'number' || !Number.isFinite(value)) throw invalid(); return value }
function modelType(value: unknown): EnterpriseModelType { if (typeof value !== 'string' || !types.includes(value as EnterpriseModelType)) throw invalid(); return value as EnterpriseModelType }
function modelFromResponse(value: unknown): EnterpriseModelProfile {
  const row = object(value)
  return { id: string(row.id), name: string(row.name), display_name: row.display_name === undefined ? undefined : string(row.display_name),
    model_type: modelType(row.model_type), version_id: string(row.version_id),
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

/** Append a version while editing the selected model's connection. */
export async function saveEnterpriseModel(tenant: string, providerId: string, profileId: string,
  input: EnterpriseModelInput, provider: EnterpriseProviderInput): Promise<void> {
  const url = `${root(tenant)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}/configuration`
  const result = object(await put(url, { ...input, provider }))
  if (string(result.id) !== profileId || !string(result.version_id)) throw invalid()
}

/** Save the model and a new shared provider together. */
export async function createEnterpriseModelWithProvider(tenant: string, provider: NewEnterpriseProvider, input: EnterpriseModelInput): Promise<void> {
  const row = object(await post(`${root(tenant)}/models`, { ...input, provider }))
  if (!string(row.id) || !string(row.version_id)) throw invalid()
}

/** Clone a shared configuration server-side, retaining its upstream model identifier. */
export async function copyEnterpriseModel(tenant: string, providerId: string, profileId: string, suffix: string): Promise<void> {
  const result = object(await post(`${root(tenant)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}/copy`, { suffix }))
  const copyId = string(result.id)
  if (!copyId || copyId === profileId || !string(result.version_id)) throw invalid()
}

/** Disable a model profile and clear defaults without deleting historical versions. */
export interface ModelUsageCounts { agents: number; knowledge_bases: number; memory: number }
export async function deleteEnterpriseModel(tenant: string, providerId: string, profileId: string): Promise<ModelUsageCounts | null> {
  const url = `${root(tenant)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}/configuration`
  try {
    const result = object(await del(url))
    if (string(result.status) !== 'disabled') throw invalid()
    return null
  } catch (error) {
    if (!error || typeof error !== 'object' || !('error' in error) || error.error == null) throw error
    const issue = object(error.error)
    if (issue.code !== 'model_in_use') throw error
    const details = object(issue.details)
    return { agents: finite(details.agents), knowledge_bases: finite(details.knowledge_bases), memory: finite(details.memory) }
  }
}

/** Set or clear one enterprise default; the backend checks type and current-version ownership. */
export async function setEnterpriseModelDefault(tenant: string, modelTypeValue: EnterpriseModelType, versionId: string | null): Promise<void> {
  const result = object(await put(`${root(tenant)}/default`, { scope: 'tenant', model_type: modelTypeValue, version_id: versionId }))
  if (string(result.status) !== 'saved') throw invalid()
}

/** Send user-entered sample data using the current saved version. */
export async function debugEnterpriseModel(tenant: string, providerId: string, profileId: string,
  input: EnterpriseModelDebugInput, file?: File): Promise<{ ok: true; result: EnterpriseModelDebugResult } | { ok: false; message: string }> {
  const url = `${root(tenant)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}/debug`
  let response: unknown
  if (file) {
    const form = new FormData()
    form.set('file', file)
    form.set('text', input.text)
    response = await postUpload(`${url}-media`, form, undefined, { timeout: 45000 })
  } else {
    response = await post(url, input)
  }
  const reply = object(response)
  if (reply.ok === false) return { ok: false, message: string(reply.message) }
  if (reply.ok !== true) throw invalid()
  const result = object(reply.result)
  if (result.type === 'chat' || result.type === 'vision' || result.type === 'speech') {
    return { ok: true, result: { type: result.type, text: string(result.text) } }
  }
  if (result.type === 'embedding') return {
    ok: true, result: { type: 'embedding', dimension: positiveInt(result.dimension), preview: array(result.preview).map(finite) },
  }
  if (result.type === 'rerank') return { ok: true, result: { type: 'rerank', scores: array(result.scores).map(value => {
    const score = object(value), index = finite(score.index)
    if (index < 0 || !Number.isSafeInteger(index)) throw invalid()
    return { index, score: finite(score.score) }
  }) } }
  throw invalid()
}

/** Test current form values using the shared provider's saved credential. */
export async function testEnterpriseModelDraft(tenant: string, provider: EnterpriseProviderInput, input: EnterpriseModelInput,
  providerId?: string): Promise<EnterpriseModelConnectionResult> {
  return connectionResult(await post(`${root(tenant)}/test`, {
    scope: 'tenant', base_url: provider.base_url,
    ...(providerId ? { provider_id: providerId } : {}),
    ...(provider.api_key ? { api_key: provider.api_key } : {}),
    model_name: input.name, model_type: input.model_type, options: input.options,
  }))
}

function connectionResult(value: unknown): EnterpriseModelConnectionResult {
  const row = object(value)
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
