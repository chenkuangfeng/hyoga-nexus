/**
 * Nexus model settings API client (apps/api `/api/v1/tenants/{tenant_id}/model-settings`).
 *
 * Replaces WeKnora's model endpoints (/api/v1/models*) for Settings → Models
 * (openspec 2026-11-05-weknora-agent-tool-model-settings, design.md section 3; spec `model-management`).
 * A WeKnora "model" maps to a Nexus provider (name, address, Key, scope) plus a model profile.
 * API Keys are write-only: they are sent once on submit and never returned or stored in the browser.
 */
import { del, get, post, put } from '@nexus-web/core/utils/request'

export type NexusModelType = 'chat' | 'embedding' | 'rerank' | 'vision' | 'speech'
export type ModelScope = 'personal' | 'tenant'

/** One model profile under a provider; `version_id` is what agents and defaults reference. */
export interface NexusModel {
  id: string
  name: string
  display_name?: string
  model_type: NexusModelType
  version_id: string
  version: number
  options: Record<string, unknown>
}

export interface NexusProvider {
  id: string
  name: string
  base_url: string
  scope: ModelScope
  key_configured: boolean
  key_mask: string
  models: NexusModel[]
}

export interface ModelSettingsView {
  providers: NexusProvider[]
  /** `defaults[scope][type] = version_id`; unset slots are absent. */
  defaults: Partial<Record<ModelScope, Partial<Record<NexusModelType, string>>>>
  can_manage_tenant: boolean
}

export interface ProviderInput {
  name: string
  base_url: string
  scope: ModelScope
  api_key?: string
}

export interface ModelInput {
  name: string
  model_type: NexusModelType
  options: Record<string, unknown>
}

export interface ConnectionResult {
  ok: boolean
  message: string
  code?: string
}

export interface DraftTestInput {
  scope: ModelScope
  base_url: string
  model_name: string
  model_type: NexusModelType
  options: Record<string, unknown>
  provider_id?: string
  api_key?: string
}

function root(tenantId: string, admin = false): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}${admin ? '/admin' : ''}/model-settings`
}

function withoutEmptyKey<T extends { api_key?: string }>(body: T): T {
  const copy = { ...body }
  if (!copy.api_key) delete copy.api_key
  return copy
}

export async function getModelSettings(tenantId: string, admin = false): Promise<ModelSettingsView> {
  const data = await get<ModelSettingsView>(root(tenantId, admin))
  if (!data || !Array.isArray(data.providers)) throw new Error('Unexpected model settings response')
  return { providers: data.providers, defaults: data.defaults || {}, can_manage_tenant: !!data.can_manage_tenant }
}

export async function createProvider(tenantId: string, body: ProviderInput): Promise<NexusProvider> {
  return post<NexusProvider>(`${root(tenantId)}/providers`, withoutEmptyKey(body))
}

/** Update metadata or rotate the Key; an omitted Key keeps the stored one (same address only). */
export async function updateProvider(tenantId: string, providerId: string, body: ProviderInput): Promise<NexusProvider> {
  return put<NexusProvider>(`${root(tenantId)}/providers/${encodeURIComponent(providerId)}`, withoutEmptyKey(body))
}

export async function addModel(tenantId: string, providerId: string, body: ModelInput): Promise<unknown> {
  return post(`${root(tenantId)}/providers/${encodeURIComponent(providerId)}/models`, body)
}

/** Append a new version; published agents keep the version they reference. */
export async function editModel(tenantId: string, providerId: string, profileId: string, body: ModelInput): Promise<unknown> {
  return put(`${root(tenantId)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}`, body)
}

/** Disable a model and clear its defaults; historical runs keep their reference. */
export async function deleteModel(tenantId: string, providerId: string, profileId: string): Promise<void> {
  await del(`${root(tenantId)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}`)
}

export async function setDefaultModel(tenantId: string, scope: ModelScope, modelType: NexusModelType,
  versionId: string | null): Promise<void> {
  await put(`${root(tenantId)}/default`, { scope, model_type: modelType, version_id: versionId })
}

export async function testDraftConnection(tenantId: string, body: DraftTestInput): Promise<ConnectionResult> {
  return post<ConnectionResult>(`${root(tenantId)}/test`, withoutEmptyKey(body))
}

export async function testSavedConnection(tenantId: string, providerId: string, profileId: string): Promise<ConnectionResult> {
  return post<ConnectionResult>(
    `${root(tenantId)}/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(profileId)}/test`, {})
}
