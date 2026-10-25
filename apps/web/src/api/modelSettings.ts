import { request, workspacePath } from './chat'
import type { ModelProvider, ModelSettings, ProviderInput, SettingsScope } from '../types/modelSettings'
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('设置数据格式无效')
  return value as Record<string, unknown>
}
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('设置数据格式无效'); return value }
function boolean(value: unknown): boolean { if (typeof value !== 'boolean') throw new Error('设置数据格式无效'); return value }
function provider(value: unknown): ModelProvider {
  const row = record(value)
  if (!Array.isArray(row.models) || !['personal', 'workspace'].includes(string(row.scope))) throw new Error('设置数据格式无效')
  return { id: string(row.id), name: string(row.name), base_url: string(row.base_url), scope: row.scope as SettingsScope,
    key_configured: boolean(row.key_configured), models: row.models.map(value => { const model = record(value)
      if (typeof model.version !== 'number' || !Number.isSafeInteger(model.version)) throw new Error('模型版本无效')
      return { id: string(model.id), name: string(model.name), version_id: string(model.version_id), version: model.version }
    }) }
}
const path = (workspace: string) => `${workspacePath(workspace)}/model-settings`
const json = (method: string, value?: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, ...(value === undefined ? {} : { body: JSON.stringify(value) }) })
const saved = (value: unknown) => { string(record(value).status) }
/** Settings requests validate public response DTOs at runtime.
 * Keys appear only in the one-time write body; callers must clear their input after submission.
 * Failures use the shared request error mapping. IDs are always escaped as path segments.
 */
export const modelSettingsApi = {
  list: (workspace: string, signal?: AbortSignal) => request<ModelSettings>(path(workspace), value => {
    const row = record(value), defaults = record(row.defaults)
    if (!Array.isArray(row.providers)) throw new Error('设置数据格式无效')
    return { providers: row.providers.map(provider), defaults: {
      ...(defaults.personal ? { personal: string(defaults.personal) } : {}),
      ...(defaults.workspace ? { workspace: string(defaults.workspace) } : {}),
    }, can_manage_workspace: boolean(row.can_manage_workspace) }
  }, { signal }),
  saveProvider: (workspace: string, value: ProviderInput, id?: string) => request(`${path(workspace)}/providers${id ? '/' + encodeURIComponent(id) : ''}`, provider, json(id ? 'PUT' : 'POST', value)),
  removeProvider: (workspace: string, id: string) => request(`${path(workspace)}/providers/${encodeURIComponent(id)}`, saved, json('DELETE')),
  saveModel: (workspace: string, provider: string, name: string, id?: string) => request(`${path(workspace)}/providers/${encodeURIComponent(provider)}/models${id ? '/' + encodeURIComponent(id) : ''}`, value => string(record(value).version_id), json(id ? 'PUT' : 'POST', { name })),
  removeModel: (workspace: string, provider: string, id: string) => request(`${path(workspace)}/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(id)}`, saved, json('DELETE')),
  setDefault: (workspace: string, scope: SettingsScope, version_id: string | null) => request(`${path(workspace)}/default`, saved, json('PUT', { scope, version_id })),
  test: (workspace: string, provider: string, model: string) => request(`${path(workspace)}/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model)}/test`, value => { const row = record(value); return { ok: boolean(row.ok), message: string(row.message) } }, json('POST')),
  createAgent: (workspace: string, name: string, instructions: string, version: string) => request(`${path(workspace)}/agents`, value => string(record(value).published_version_id), json('POST', { name, instructions, model_profile_version_id: version })),
}
