import { get, put } from '@nexus-web/core/utils/request'
import type { AgentSandboxProfile } from './nexus-agents'

export interface SandboxPolicy {
  paused: boolean
  exec_timeout_max_seconds: number
  skill_timeout_seconds: number
  skill_timeout_max_seconds: number
}

export interface SandboxDetails extends AgentSandboxProfile {
  editable: boolean
  policy: SandboxPolicy
  network: 'none' | 'bridge' | null
  image: string | null
  remote_profile: string | null
  workspace_quota_mb: number
  limits: { cpus?: number; memory_mb?: number; pids?: number }
  background: boolean
  build: boolean
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
