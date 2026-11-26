import { del, get, post, put } from '@nexus-web/core/utils/request'
import type { AgentSandboxProfile } from './nexus-agents'

export interface SandboxPolicy {
  paused: boolean
  exec_timeout_max_seconds: number
  skill_timeout_seconds: number
  skill_timeout_max_seconds: number
}

export type SandboxBackend = AgentSandboxProfile['type']
export type SandboxConfiguration = Record<string, string | number | boolean | string[]>
export interface SandboxDetails extends AgentSandboxProfile {
  description?: string
  revision?: number
  configuration?: SandboxConfiguration | null
  editable: boolean
  policy: SandboxPolicy
  network: 'none' | 'bridge' | null
  image: string | null
  remote_profile: string | null
  workspace_quota_mb: number
  limits: { cpus?: number; memory_mb?: number; pids?: number }
  background: boolean
  build: boolean
  connection?: {
    policy_digest: string
    provider: 'docker' | 'e2b' | 'cubesandbox'
    file_transfer: 'snapshot' | 'shared_volume'
    output_capture: 'bounded'
    cleanup: 'persistent'
    connected_at: string
    template_revision: string | null
  } | null
  acceptance: { checked_at: string; passed: boolean; items: { name: string; ok: boolean }[] } | null
}

const profilePath = (tenant: string, profile: string) =>
  `/api/v1/tenants/${encodeURIComponent(tenant)}/admin/sandboxes/${encodeURIComponent(profile)}`

export function getSandboxDetails(tenant: string, profile: string): Promise<SandboxDetails> {
  return get<SandboxDetails>(profilePath(tenant, profile))
}

export function updateSandboxPolicy(tenant: string, profile: string, policy: SandboxPolicy): Promise<SandboxDetails> {
  return put<SandboxDetails>(`${profilePath(tenant, profile)}/policy`, policy)
}

export function connectSandbox(tenant: string, profile: string): Promise<SandboxDetails> {
  return post<SandboxDetails>(`${profilePath(tenant, profile)}/connect`, {})
}

export interface GatewayProvider {
  type: 'docker' | 'e2b' | 'cubesandbox'
  template: string
  domain: string
  revision: string
  has_api_key: boolean
}
export interface GatewayExecution {
  id: string
  state: 'creating' | 'preparing' | 'running' | 'cleanup_pending' | 'finished' | 'cancelled'
  created_at: number
  updated_at: number
}

export function getGatewayProvider(tenant: string, profile: string): Promise<GatewayProvider> {
  return get<GatewayProvider>(`${profilePath(tenant, profile)}/provider`)
}
export function saveGatewayProvider(tenant: string, profile: string, values: {
  type: 'e2b' | 'cubesandbox'; template: string; domain: string; revision: string; api_key?: string
}): Promise<GatewayProvider> {
  return put<GatewayProvider>(`${profilePath(tenant, profile)}/provider`, values)
}
export function getGatewayExecutions(tenant: string, profile: string): Promise<{ items: GatewayExecution[] }> {
  return get<{ items: GatewayExecution[] }>(`${profilePath(tenant, profile)}/executions`)
}
export function retryGatewayCleanup(tenant: string, profile: string, id: string): Promise<Pick<GatewayExecution, 'id' | 'state'>> {
  return post<Pick<GatewayExecution, 'id' | 'state'>>(`${profilePath(tenant, profile)}/executions/${encodeURIComponent(id)}/cleanup`, {})
}


export interface SandboxCatalog {
  items: SandboxDetails[]
  can_manage: boolean
  enabled: boolean
  revision: number
  defaults: Record<SandboxBackend, SandboxConfiguration>
}
const collectionPath = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}/admin/sandboxes`

export function listSandboxProfiles(tenant: string): Promise<SandboxCatalog> {
  return get<SandboxCatalog>(collectionPath(tenant))
}
export function saveSandboxConfiguration(tenant: string, name: string | null, values: SandboxConfiguration,
  revision: number): Promise<SandboxDetails> {
  const body = { values, revision }
  return name ? put<SandboxDetails>(`${profilePath(tenant, name)}/configuration`, body)
    : post<SandboxDetails>(collectionPath(tenant), body)
}
export function deleteSandboxConfiguration(tenant: string, name: string, revision: number): Promise<void> {
  return del<void>(`${profilePath(tenant, name)}?revision=${revision}`)
}
