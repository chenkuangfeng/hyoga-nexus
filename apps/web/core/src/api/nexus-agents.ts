/**
 * Nexus agent editor API client (apps/api `/api/v1/tenants/{tenant_id}/agents*`, `/agent-tools`).
 *
 * Replaces WeKnora's agent endpoints (/api/v1/agents*) for the agent list and editor
 * (openspec 2026-11-05-weknora-agent-tool-model-settings). Every function takes the space id
 * explicitly. Authorization is decided by the server on every call; the page never caches it.
 */
import { del, get, getDown, post, put } from '@nexus-web/core/utils/request'

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
  ownership?: 'personal' | 'enterprise'
  can_maintain?: boolean
  owned_by_me?: boolean
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
  'sandbox_disabled' | 'sandbox_not_accepted' | 'sandbox_local_not_allowed' | 'sandbox_profile_unknown' | 'sandbox_ssh_not_allowed' | 'sandbox_profile_paused' | ''

/** One sandbox profile the operator defined (`sandbox_profiles` of `GET /agent-tools`); an agent picks one by name. */
export interface AgentSandboxProfile {
  name: string
  type: 'local' | 'docker' | 'bwrap' | 'ssh' | 'managed'
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

export async function getAgentToolCatalog(tenantId: string, admin = false): Promise<AgentToolCatalog> {
  const data: unknown = await get(`${tenantPath(tenantId)}${admin ? '/admin' : ''}/agent-tools`)
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Unexpected tool catalog response')
  const value = data as Record<string, unknown>
  if (!Array.isArray(value.tools) || !value.tools.every(isAgentToolEntry)
      || !Array.isArray(value.groups) || !value.groups.every((item) => typeof item === 'string')
      || !Array.isArray(value.default_tools) || !value.default_tools.every((item) => typeof item === 'string')
      || typeof value.can_enable_tools !== 'boolean') throw new Error('Unexpected tool catalog response')
  return value as unknown as AgentToolCatalog
}

function isAgentToolEntry(value: unknown): value is AgentToolEntry {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const row = value as Record<string, unknown>
  return typeof row.name === 'string' && typeof row.description === 'string' && typeof row.group === 'string'
    && ['low', 'medium', 'high'].includes(String(row.risk_level))
    && typeof row.read_only === 'boolean' && typeof row.requires_approval === 'boolean'
    && typeof row.side_effects === 'boolean' && typeof row.enabled_in_tenant === 'boolean'
    && (row.builtin === undefined || typeof row.builtin === 'boolean')
    && (row.disabled === undefined || typeof row.disabled === 'boolean')
}

/** Enable a builtin tool for the whole space (owner/admin; the server checks `tools:manage`). */
export async function enableTenantTool(tenantId: string, name: string, admin = false): Promise<void> {
  await post(`${tenantPath(tenantId)}${admin ? '/admin' : ''}/tools/${encodeURIComponent(name)}/enable`, {})
}

/** Stop offering a builtin tool or skill in this space only (owner/admin). Published agents keep their bindings. */
export async function disableBuiltinResource(tenantId: string, kind: 'tool' | 'skill', resourceId: string, admin = false): Promise<void> {
  await put(`${tenantPath(tenantId)}${admin ? '/admin' : ''}/builtin-disabled/${kind}/${encodeURIComponent(resourceId)}`, {})
}

/** Offer a switched-off builtin tool or skill in this space again. */
export async function restoreBuiltinResource(tenantId: string, kind: 'tool' | 'skill', resourceId: string, admin = false): Promise<void> {
  await del(`${tenantPath(tenantId)}${admin ? '/admin' : ''}/builtin-disabled/${kind}/${encodeURIComponent(resourceId)}`)
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
  /** Uses by the whole space and the latest use; `null` for builtin skills, which are used in every space. */
  use_count?: number | null
  last_used_at?: string | null
  /** Scan verdict of the current version (`safe` / `caution` / `dangerous`), who published it, and whether the scanner has moved on. */
  verdict?: string | null
  trust?: string | null
  rescan_needed?: boolean
  /** Only when a sandbox profile was asked for: whether the skill's scripts can run there. `null` = it ships no scripts. */
  run?: { ok: boolean, reason: string } | null
}

/** `sandboxProfile` is a profile name; `''` means the deployment's default. Leave it out to skip the run check. */
export async function listTenantSkills(tenantId: string, sandboxProfile?: string): Promise<TenantSkill[]> {
  const query = sandboxProfile === undefined ? '' : `?sandbox_profile=${encodeURIComponent(sandboxProfile)}`
  const data: unknown = await get(`${tenantPath(tenantId)}/skills${query}`)
  if (!Array.isArray(data)) throw new Error('Unexpected skill list response')
  return data as TenantSkill[]
}

export async function getNativeDefaults(tenantId: string): Promise<NativeDefaults> {
  return get<NativeDefaults>(`${tenantPath(tenantId)}/native/settings`)
}

// ---- Skill installation (openspec 2026-11-07-skill-evolution, S3) ------------------------------------------

/** Result of installing a skill. `build_state` is `installing` while its dependencies are being built. */
export interface SkillInstallResult {
  skill: string
  version: number
  version_id: string
  verdict: string
  findings: number
  notes: string[]
  binary_files: string[]
  build_state: 'ready' | 'installing' | string
}

/** Build state of one skill version, polled while `installing`. */
export interface SkillInstallStatus {
  skill: string
  version: number
  build_state: 'installing' | 'ready' | 'failed' | string
  build_error: string | null
  build_log: string
  env_ref: string | null
}

function skillPath(tenantId: string, name: string): string {
  return `${tenantPath(tenantId)}/skills/${encodeURIComponent(name)}`
}

/** Install a skill from a zip (the raw request body). Administrators; `acknowledge` releases scan findings. */
export async function uploadSkillBundle(tenantId: string, file: Blob, options: {
  sandboxProfile?: string, acknowledge?: boolean } = {}): Promise<SkillInstallResult> {
  const query = new URLSearchParams()
  if (options.acknowledge) query.set('acknowledge_findings', 'true')
  if (options.sandboxProfile) query.set('sandbox_profile', options.sandboxProfile)
  const suffix = query.toString() ? `?${query}` : ''
  const data: unknown = await post(`${tenantPath(tenantId)}/skills/upload${suffix}`, file,
    { headers: { 'Content-Type': 'application/zip' }, timeout: 120_000 })
  return data as SkillInstallResult
}

/** Ask the server to fetch a skill from a remote source. `confirm` must be true: the user has seen the address. */
export async function installRemoteSkill(tenantId: string, source: string, options: {
  confirm: boolean, acknowledge?: boolean }): Promise<SkillInstallResult> {
  const data: unknown = await post(`${tenantPath(tenantId)}/skills/install-remote`, {
    source, confirm: options.confirm, acknowledge_findings: !!options.acknowledge }, { timeout: 360_000 })
  return data as SkillInstallResult
}

export async function getSkillInstallStatus(tenantId: string, name: string, version: number): Promise<SkillInstallStatus> {
  const data: unknown = await get(`${skillPath(tenantId, name)}/versions/${version}/install`)
  return data as SkillInstallStatus
}

export async function reinstallSkill(tenantId: string, name: string, version: number, sandboxProfile?: string): Promise<void> {
  const query = sandboxProfile ? `?sandbox_profile=${encodeURIComponent(sandboxProfile)}` : ''
  await post(`${skillPath(tenantId, name)}/versions/${version}/reinstall${query}`, {})
}

export async function stopSkillInstall(tenantId: string, name: string, version: number): Promise<void> {
  await post(`${skillPath(tenantId, name)}/versions/${version}/stop-install`, {})
}

// ---- Private skills (openspec 2026-11-07-skill-evolution, S4) ------------------------------------------------

/** One of the caller's private skills. Only the owner ever receives these. */
export interface MySkill {
  name: string
  version: number | null
  description: string
  verdict: string | null
  model_invocable: boolean
  archived: boolean
  /** The space library or a builtin skill now uses this name, so the private one is no longer offered. */
  superseded: boolean
  latest_version: number | null
  /** Build state of the newest version (`installing` / `ready` / `failed`). */
  latest_state: string | null
  latest_error: string | null
  /** This user's own loads of the skill and the latest use. */
  use_count: number
  last_used_at: string | null
  created_at: string
}

export interface MySkillDraft { name: string, files: string[], updated_at: string, editing: boolean }
export interface MySkillVersion {
  version: number, version_id: string, content_hash: string, build_state: string, build_error: string | null,
  verdict: string, current: boolean, created_at: string
}

function mySkillPath(tenantId: string, name: string): string {
  return `${tenantPath(tenantId)}/my-skills/${encodeURIComponent(name)}`
}

export async function listMySkills(tenantId: string): Promise<{ skills: MySkill[], drafts: MySkillDraft[] }> {
  const data: unknown = await get(`${tenantPath(tenantId)}/my-skills`)
  return data as { skills: MySkill[], drafts: MySkillDraft[] }
}

export async function listMySkillVersions(tenantId: string, name: string): Promise<MySkillVersion[]> {
  const data: unknown = await get(`${mySkillPath(tenantId, name)}/versions`)
  return Array.isArray(data) ? data as MySkillVersion[] : []
}

export async function rollbackMySkill(tenantId: string, name: string, version: number): Promise<void> {
  await post(`${mySkillPath(tenantId, name)}/rollback`, { version })
}

export async function archiveMySkill(tenantId: string, name: string): Promise<void> {
  await post(`${mySkillPath(tenantId, name)}/archive`, {})
}

export async function restoreMySkill(tenantId: string, name: string): Promise<void> {
  await post(`${mySkillPath(tenantId, name)}/restore`, {})
}

export async function deleteMySkillDraft(tenantId: string, name: string): Promise<void> {
  await del(`${tenantPath(tenantId)}/my-skill-drafts/${encodeURIComponent(name)}`)
}

// ---- Sharing skills into the space library (openspec 2026-11-07-skill-evolution, S5) -----------------------------

export interface SkillSubmission {
  id: string
  name: string
  description: string
  origin: string
  state: 'pending' | 'approved' | 'rejected' | 'superseded' | 'withdrawn' | string
  verdict: string
  findings: number
  submitted_by: string
  review_reason: string
  created_at: string
  reviewed_at: string | null
  published_version_id: string | null
  /** The name already exists in the library (a submission against an earlier submission's skill). */
  updates_existing: boolean
}

/** What a reviewer reads. All strings are plain text and must be rendered as text, never as markup. */
export interface SkillSubmissionReview extends SkillSubmission {
  skill_md: string
  files: Record<string, string>
  scan: { verdict: string, findings: Array<{ rule: string, severity: string, path: string, line: number | null, excerpt: string }> }
  diff: string
  library_moved: boolean
  notice: string
}

function submissionPath(tenantId: string, id?: string): string {
  return `${tenantPath(tenantId)}/skill-submissions${id ? `/${encodeURIComponent(id)}` : ''}`
}

/** The caller's API permission keys in this space (`tools:manage`, `skills:submit` ...). */
export async function getMyApiPermissions(tenantId: string): Promise<string[]> {
  const data = await get<{ apis?: string[] }>(`${tenantPath(tenantId)}/me/permissions`)
  return Array.isArray(data?.apis) ? data.apis : []
}

export async function submitMySkill(tenantId: string, fromPrivate: string): Promise<SkillSubmission> {
  return await post(submissionPath(tenantId), { from_private: fromPrivate }) as unknown as SkillSubmission
}

export async function shareMySkill(tenantId: string, name: string, sandboxProfile?: string): Promise<void> {
  const query = sandboxProfile ? `?sandbox_profile=${encodeURIComponent(sandboxProfile)}` : ''
  await post(`${tenantPath(tenantId)}/my-skills/${encodeURIComponent(name)}/share${query}`, {})
}

export async function listMySubmissions(tenantId: string): Promise<SkillSubmission[]> {
  const data: unknown = await get(`${submissionPath(tenantId)}?mine=true`)
  return Array.isArray(data) ? data as SkillSubmission[] : []
}

export async function withdrawSubmission(tenantId: string, id: string): Promise<void> {
  await post(`${submissionPath(tenantId, id)}/withdraw`, {})
}

export async function listReviewQueue(tenantId: string): Promise<SkillSubmission[]> {
  const data: unknown = await get(`${submissionPath(tenantId)}?state=pending`)
  return Array.isArray(data) ? data as SkillSubmission[] : []
}

export async function getSubmissionReview(tenantId: string, id: string): Promise<SkillSubmissionReview> {
  return await get(`${submissionPath(tenantId, id)}/review`) as unknown as SkillSubmissionReview
}

export async function approveSubmission(tenantId: string, id: string): Promise<void> {
  await post(`${submissionPath(tenantId, id)}/approve`, {}, { timeout: 120_000 })
}

export async function rejectSubmission(tenantId: string, id: string, reason: string): Promise<void> {
  await post(`${submissionPath(tenantId, id)}/reject`, { reason })
}


// ---- Toolbox skill library (openspec 2026-11-08-toolbox) --------------------------------------------------------

/** One version row of `GET /skills/{name}/versions`. */
export interface SkillVersionInfo {
  version: number
  version_id: string
  content_hash: string
  description: string
  tools: string[]
  trust: string
  verdict: string
  findings: unknown[]
  rescan_needed: boolean
  build_state: string
  has_bundle: boolean
  origin: { kind?: string, label?: string } | null
  created_at: string
}

export async function listSkillVersions(tenantId: string, name: string): Promise<SkillVersionInfo[]> {
  const data: unknown = await get(`${skillPath(tenantId, name)}/versions`)
  return Array.isArray(data) ? data as SkillVersionInfo[] : []
}

/** Scan one version again with the current scanner (needs `tools:manage`); the version itself does not change. */
export async function rescanSkillVersion(tenantId: string, name: string, version: number): Promise<void> {
  await post(`${skillPath(tenantId, name)}/versions/${version}/rescan`, {})
}

/** The zip of a skill (the current version by default). */
export async function downloadSkillBundle(tenantId: string, name: string, version?: number): Promise<Blob> {
  const query = version ? `?version=${version}` : ''
  return await getDown(`${skillPath(tenantId, name)}/bundle${query}`)
}
