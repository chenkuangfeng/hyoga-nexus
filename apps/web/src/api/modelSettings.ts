import { request, tenantPath } from './chat'
import type { ModelProvider, ModelSettings, ProviderInput, SettingsScope } from '../types/modelSettings'
import { i18n } from '../i18n'
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(i18n.global.t('errors.dataInvalid'))
  return value as Record<string, unknown>
}
function string(value: unknown): string { if (typeof value !== 'string') throw new Error(i18n.global.t('errors.dataInvalid')); return value }
function boolean(value: unknown): boolean { if (typeof value !== 'boolean') throw new Error(i18n.global.t('errors.dataInvalid')); return value }
function provider(value: unknown): ModelProvider {
  const row = record(value)
  if (!Array.isArray(row.models) || !['personal', 'tenant'].includes(string(row.scope))) throw new Error(i18n.global.t('errors.dataInvalid'))
  return { id: string(row.id), name: string(row.name), base_url: string(row.base_url), scope: row.scope as SettingsScope,
    key_configured: boolean(row.key_configured), models: row.models.map(value => { const model = record(value)
      if (typeof model.version !== 'number' || !Number.isSafeInteger(model.version)) throw new Error(i18n.global.t('errors.modelVersionInvalid'))
      return { id: string(model.id), name: string(model.name), version_id: string(model.version_id), version: model.version, options: model.options === undefined ? {} : record(model.options) }
    }) }
}
const path = (tenant: string) => `${tenantPath(tenant)}/model-settings`
const json = (method: string, value?: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, ...(value === undefined ? {} : { body: JSON.stringify(value) }) })
const saved = (value: unknown) => { string(record(value).status) }
/** Settings requests validate public response DTOs at runtime.
 * Keys appear only in the one-time write body; callers must clear their input after submission.
 * Failures use the shared request error mapping. IDs are always escaped as path segments.
 */
export const modelSettingsApi = {
  list: (tenant: string, signal?: AbortSignal) => request<ModelSettings>(path(tenant), value => {
    const row = record(value), defaults = record(row.defaults)
    if (!Array.isArray(row.providers)) throw new Error(i18n.global.t('errors.dataInvalid'))
    return { providers: row.providers.map(provider), defaults: {
      ...(defaults.personal ? { personal: string(defaults.personal) } : {}),
      ...(defaults.tenant ? { tenant: string(defaults.tenant) } : {}),
    }, can_manage_tenant: boolean(row.can_manage_tenant) }
  }, { signal }),
  saveProvider: (tenant: string, value: ProviderInput, id?: string) => request(`${path(tenant)}/providers${id ? '/' + encodeURIComponent(id) : ''}`, provider, json(id ? 'PUT' : 'POST', value)),
  removeProvider: (tenant: string, id: string) => request(`${path(tenant)}/providers/${encodeURIComponent(id)}`, saved, json('DELETE')),
  saveModel: (tenant: string, provider: string, name: string, id?: string, options?: Record<string, unknown>) => request(`${path(tenant)}/providers/${encodeURIComponent(provider)}/models${id ? '/' + encodeURIComponent(id) : ''}`, value => string(record(value).version_id), json(id ? 'PUT' : 'POST', { name, ...(options ? { options } : {}) })),
  removeModel: (tenant: string, provider: string, id: string) => request(`${path(tenant)}/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(id)}`, saved, json('DELETE')),
  setDefault: (tenant: string, scope: SettingsScope, version_id: string | null) => request(`${path(tenant)}/default`, saved, json('PUT', { scope, version_id })),
  test: (tenant: string, provider: string, model: string) => request(`${path(tenant)}/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model)}/test`, value => { const row = record(value); return { ok: boolean(row.ok), message: string(row.message) } }, json('POST')),
  createAgent: (tenant: string, name: string, instructions: string, version: string) => request(`${path(tenant)}/agents`, value => string(record(value).published_version_id), json('POST', { name, instructions, model_profile_version_id: version })),
}
