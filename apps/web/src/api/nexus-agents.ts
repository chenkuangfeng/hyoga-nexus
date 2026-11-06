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
  enabled_in_tenant: boolean
}

export interface AgentToolCatalog {
  tools: AgentToolEntry[]
  groups: string[]
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

export async function getNativeDefaults(tenantId: string): Promise<NativeDefaults> {
  return get<NativeDefaults>(`${tenantPath(tenantId)}/native/settings`)
}
