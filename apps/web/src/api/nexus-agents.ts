/**
 * Nexus agent editor API client (apps/api `/api/v1/tenants/{tenant_id}/agents*`, `/agent-tools`).
 *
 * Replaces WeKnora's agent endpoints (/api/v1/agents*) for the agent list and editor
 * (openspec 2026-11-05-weknora-agent-tool-model-settings). Every function takes the space id
 * explicitly. Authorization is decided by the server on every call; the page never caches it.
 */
import { del, get, post, put } from '@/utils/request'

/** One resource binding of an agent draft or version. Only `kind = tool` is edited here. */
export interface AgentResourceBinding {
  kind: string
  resource_id: string
  resource_version_id: string | null
  source_tenant_id: string
  config: Record<string, unknown>
}

/** `AgentView` returned by the platform API. Admins see the draft; members see the published version. */
export interface NexusAgent {
  id: string
  tenant_id: string
  name: string
  description: string
  status: 'draft' | 'published' | 'archived' | string
  published_version_id: string | null
  version_counter: number
  runtime_type: string
  instructions: string
  model_profile_version_id: string | null
  budgets: Record<string, unknown>
  resource_bindings: AgentResourceBinding[]
  created_at: string
  updated_at: string
}

/** Body of `POST /agents` and `PUT /agents/{id}` (`AgentDraftInput`). */
export interface AgentDraftInput {
  name: string
  description: string
  runtime_type: 'native'
  instructions: string
  model_profile_version_id: string
  budgets: Record<string, unknown>
  resource_bindings: Array<Omit<AgentResourceBinding, 'source_tenant_id'> & { source_tenant_id?: string }>
}

/** One entry of `GET /agent-tools`; flags mirror the tool's `ToolDefinition`. */
export interface AgentToolEntry {
  name: string
  description: string
  group: string
  /** `read` / `probe` / `write` / `destructive` (tool-call-hardening D10). */
  risk?: 'read' | 'probe' | 'write' | 'destructive'
  risk_level: 'low' | 'medium' | 'high'
  read_only: boolean
  requires_approval: boolean
  side_effects: boolean
  /** Assignable in this space: a builtin tool is, unless the space switched it off; "enabled" never means an agent uses it. */
  enabled_in_tenant: boolean
  /** Registered under the system space, so every space (personal ones too) can assign it. */
  builtin?: boolean
  /** This space switched the builtin tool off (openspec 2026-11-07-skill-evolution). */
  disabled?: boolean
}

/**
 * One tool group of `GET /agent-tools` (openspec 2026-11-07-tool-expansion). `available` is the deployment side
 * (sandbox accepted, web enabled...) and `reason` its stable code; `default_enabled` is the agent-side default of
 * `behavior.tool_groups_enabled`; a group with no tools yet carries the phase that delivers them in `planned`.
 */
export interface AgentToolGroupInfo {
  id: string
  label: string
  default_enabled: boolean
  locked: boolean
  tool_count: number
  planned: string
  available: boolean
  reason: string
}

/** Why a sandbox profile cannot be used right now (stable codes of the platform's tool gates). */
export type SandboxProfileReason =
  'sandbox_disabled' | 'sandbox_not_accepted' | 'sandbox_local_not_allowed' | 'sandbox_profile_unknown' | ''

/** One sandbox profile the operator defined (`sandbox_profiles` of `GET /agent-tools`); an agent picks one by name. */
export interface AgentSandboxProfile {
  name: string
  type: 'local' | 'docker' | 'bwrap'
  default: boolean
  available: boolean
  reason: SandboxProfileReason | string
}

export interface AgentToolCatalog {
  tools: AgentToolEntry[]
  groups: string[]
  group_info?: AgentToolGroupInfo[]
  /** Empty when the sandbox is off or its configuration is broken. */
  sandbox_profiles?: AgentSandboxProfile[]
  /** The caller's Native default `enabled_tools`, used to preselect tools for a new agent. */
  default_tools: string[]
  /** Whether the caller may enable a tool for the space (owner or admin). */
  can_enable_tools: boolean
}

/** Native personal defaults (`GET /native/settings`), used as initial values of a new agent. */
export interface NativeDefaults {
  version: number
  settings: { budgets: Record<string, number>; behavior: Record<string, unknown> }
}

function tenantPath(tenantId: string): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}`
}

function agentPath(tenantId: string, agentId: string): string {
  return `${tenantPath(tenantId)}/agents/${encodeURIComponent(agentId)}`
}

export async function listNexusAgents(tenantId: string): Promise<NexusAgent[]> {
  const data: unknown = await get(`${tenantPath(tenantId)}/agents`)
  if (!Array.isArray(data)) throw new Error('Unexpected agent list response')
  return data as NexusAgent[]
}

export async function getNexusAgent(tenantId: string, agentId: string): Promise<NexusAgent> {
  return get<NexusAgent>(agentPath(tenantId, agentId))
}

export async function createNexusAgent(tenantId: string, body: AgentDraftInput): Promise<NexusAgent> {
  return post<NexusAgent>(`${tenantPath(tenantId)}/agents`, body)
}

export async function updateNexusAgent(tenantId: string, agentId: string, body: AgentDraftInput): Promise<NexusAgent> {
  return put<NexusAgent>(agentPath(tenantId, agentId), body)
}

/** Publish the current draft as a new immutable version; existing sessions keep their version. */
export async function publishNexusAgent(tenantId: string, agentId: string): Promise<{ id: string; version: number }> {
  return post<{ id: string; version: number }>(`${agentPath(tenantId, agentId)}/publish`, {})
}

/** Archive (soft delete). Existing sessions stay readable but accept no new Runs. */
export async function archiveNexusAgent(tenantId: string, agentId: string): Promise<void> {
  await del(agentPath(tenantId, agentId))
}

/** Copy the draft into a new unpublished agent. Shares and versions are not copied. */
export async function copyNexusAgent(tenantId: string, agentId: string, name?: string): Promise<NexusAgent> {
  return post<NexusAgent>(`${agentPath(tenantId, agentId)}/copy`, name ? { name } : {})
}

export async function getAgentToolCatalog(tenantId: string): Promise<AgentToolCatalog> {
  const data = await get<AgentToolCatalog>(`${tenantPath(tenantId)}/agent-tools`)
  if (!data || !Array.isArray(data.tools)) throw new Error('Unexpected tool catalog response')
  return data
}

/** Enable a builtin tool for the whole space (owner/admin; the server checks `tools:manage`). */
export async function enableTenantTool(tenantId: string, name: string): Promise<void> {
  await post(`${tenantPath(tenantId)}/tools/${encodeURIComponent(name)}/enable`, {})
}

/** Stop offering a builtin tool or skill in this space only (owner/admin). Published agents keep their bindings. */
export async function disableBuiltinResource(tenantId: string, kind: 'tool' | 'skill', resourceId: string): Promise<void> {
  await put(`${tenantPath(tenantId)}/builtin-disabled/${kind}/${encodeURIComponent(resourceId)}`, {})
}

/** Offer a switched-off builtin tool or skill in this space again. */
export async function restoreBuiltinResource(tenantId: string, kind: 'tool' | 'skill', resourceId: string): Promise<void> {
  await del(`${tenantPath(tenantId)}/builtin-disabled/${kind}/${encodeURIComponent(resourceId)}`)
}

/**
 * One entry of `GET /skills`: the space's own skills and the builtin ones. A builtin skill (`scope = 'builtin'`) is
 * registered under the system space, so binding it uses its `source_tenant_id`. `disabled` marks one this space
 * switched off. `version_id` and `tools` are what an agent binds and what must be bound beside it.
 */
export interface TenantSkill {
  name: string
  source: string
  scope: 'builtin' | 'space'
  source_tenant_id: string
  version: number | null
  version_id: string | null
  tools: string[]
  execution: 'sandbox' | 'local'
  model_invocable: boolean
  description: string
  disabled: boolean
}

export async function listTenantSkills(tenantId: string): Promise<TenantSkill[]> {
  const data: unknown = await get(`${tenantPath(tenantId)}/skills`)
  if (!Array.isArray(data)) throw new Error('Unexpected skill list response')
  return data as TenantSkill[]
}

export async function getNativeDefaults(tenantId: string): Promise<NativeDefaults> {
  return get<NativeDefaults>(`${tenantPath(tenantId)}/native/settings`)
}
