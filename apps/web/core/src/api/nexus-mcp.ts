/**
 * Nexus MCP service management client (apps/api `/api/v1/tenants/{tenant_id}/mcp-services`,
 * openspec 2026-11-08-mcp, tasks 4.1–4.2).
 *
 * Not to be confused with `mcp-service.ts`, which still targets WeKnora's `/api/v1/mcp-services`
 * shapes used by the legacy settings dialog. This module mirrors the Nexus response bodies:
 * service rows carry a normalized `config` (credential-reference markers included, resolved
 * secrets never returned), and tool rows carry enablement plus the effective risk the server
 * derived from the service's annotations and the workspace policy.
 *
 * Authorization is decided by the server on every call: listing and tool reads need active
 * membership, while create/update/delete/discover/enablement need `tools:manage`.
 */
import { del, get, patch, post, put } from '@nexus-web/core/utils/request'

export type McpTransport = 'stdio' | 'streamable_http' | 'sse'

/** Static credentials are the default; `oauth` adds a per-principal bearer token at call time. */
export type McpAuthType = 'none' | 'oauth'

/** A header/env value that names a stored credential instead of carrying the secret itself. */
export interface McpCredentialReference {
  $credential_ref: string
}

export type McpConfigValue = string | McpCredentialReference

/** Non-secret OAuth settings; access tokens live per (tenant, principal, service) on the server. */
export interface McpOAuthConfig {
  scopes?: string[]
  client_id?: string | null
  client_secret?: string | McpCredentialReference | null
  auth_server_metadata_url?: string | null
}

/** The normalized connection config stored for one service (`transport` echoes the row's transport). */
export interface McpConnectionConfig {
  transport?: McpTransport
  timeout?: number
  auth_type?: McpAuthType
  url?: string
  headers?: Record<string, McpConfigValue>
  command?: string
  args?: string[]
  env?: Record<string, McpConfigValue>
  sse_read_timeout?: number
  oauth?: McpOAuthConfig
}

export interface McpService {
  id: string
  tenant_id: string
  name: string
  description: string
  transport: McpTransport
  config: McpConnectionConfig
  enabled: boolean
  /** Changes whenever the connection parameters change; cached tools and sessions key off it. */
  config_epoch: string
  created_by: string
  created_at: string
  updated_at: string
}

export interface McpServiceInput {
  name: string
  description: string
  transport: McpTransport
  config: McpConnectionConfig
}

export interface McpServiceUpdateInput extends Partial<McpServiceInput> {
  enabled?: boolean
}

/** `read` only when the service sets `readOnlyHint`; `destructive` is a workspace-only choice. */
export type McpToolRisk = 'read' | 'write' | 'destructive'

export interface McpServiceTool {
  tool_name: string
  description: string
  enabled: boolean
  read_only_hint: boolean
  catalog_status: 'ready' | 'error' | string
  catalog_error: string | null
  explicit_risk: McpToolRisk | null
  observed_risk: McpToolRisk | null
  effective_risk: McpToolRisk
  require_approval: boolean
  /** The service now declares lower than the observed maximum; only the workspace can accept it. */
  pending_downgrade: boolean
}

export interface McpDiscoveryResult {
  service_id: string
  /** Discovered tool names, all disabled until an administrator enables them. */
  tools: string[]
  fingerprint: string
}

const badResponse = () => new Error('mcp_response_invalid')
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw badResponse()
  return value as Record<string, unknown>
}
function text(value: unknown): string { if (typeof value !== 'string') throw badResponse(); return value }
function flag(value: unknown): boolean { if (typeof value !== 'boolean') throw badResponse(); return value }
function textList(value: unknown): string[] {
  if (!Array.isArray(value)) throw badResponse()
  return value.map(text)
}
function configFromResponse(value: unknown): McpConnectionConfig {
  const row = record(value), config: McpConnectionConfig = {}
  if (row.transport !== undefined) {
    if (row.transport !== 'stdio' && row.transport !== 'streamable_http' && row.transport !== 'sse') throw badResponse()
    config.transport = row.transport
  }
  if (row.timeout !== undefined) {
    if (typeof row.timeout !== 'number' || !Number.isFinite(row.timeout) || row.timeout <= 0) throw badResponse()
    config.timeout = row.timeout
  }
  if (row.auth_type !== undefined) {
    if (row.auth_type !== 'none' && row.auth_type !== 'oauth') throw badResponse()
    config.auth_type = row.auth_type
  }
  for (const key of ['url', 'command'] as const) if (row[key] !== undefined) config[key] = text(row[key])
  if (row.args !== undefined) config.args = textList(row.args)
  if (row.sse_read_timeout !== undefined) {
    if (typeof row.sse_read_timeout !== 'number' || !Number.isFinite(row.sse_read_timeout) || row.sse_read_timeout <= 0) throw badResponse()
    config.sse_read_timeout = row.sse_read_timeout
  }
  for (const key of ['headers', 'env'] as const) {
    if (row[key] === undefined) continue
    const values = record(row[key]), parsed: Record<string, McpConfigValue> = {}
    for (const [name, raw] of Object.entries(values)) {
      if (typeof raw === 'string') parsed[name] = raw
      else {
        const reference = record(raw)
        if (Object.keys(reference).length !== 1 || typeof reference.$credential_ref !== 'string') throw badResponse()
        parsed[name] = { $credential_ref: reference.$credential_ref }
      }
    }
    config[key] = parsed
  }
  if (row.oauth !== undefined) {
    const oauth = record(row.oauth), result: McpOAuthConfig = {}
    if (oauth.scopes !== undefined) result.scopes = textList(oauth.scopes)
    if (oauth.client_id !== undefined) result.client_id = oauth.client_id === null ? null : text(oauth.client_id)
    if (oauth.auth_server_metadata_url !== undefined) result.auth_server_metadata_url = oauth.auth_server_metadata_url === null ? null : text(oauth.auth_server_metadata_url)
    if (oauth.client_secret !== undefined) {
      if (oauth.client_secret === null || typeof oauth.client_secret === 'string') result.client_secret = oauth.client_secret
      else {
        const reference = record(oauth.client_secret)
        if (Object.keys(reference).length !== 1 || typeof reference.$credential_ref !== 'string') throw badResponse()
        result.client_secret = { $credential_ref: reference.$credential_ref }
      }
    }
    config.oauth = result
  }
  return config
}
function serviceFromResponse(value: unknown): McpService {
  const row = record(value)
  if (row.transport !== 'stdio' && row.transport !== 'streamable_http' && row.transport !== 'sse') throw badResponse()
  return {
    id: text(row.id), tenant_id: text(row.tenant_id), name: text(row.name), description: text(row.description),
    transport: row.transport, config: configFromResponse(row.config), enabled: flag(row.enabled),
    config_epoch: text(row.config_epoch), created_by: text(row.created_by), created_at: text(row.created_at), updated_at: text(row.updated_at),
  }
}
function toolFromResponse(value: unknown): McpServiceTool {
  const row = record(value)
  const risks = ['read', 'write', 'destructive']
  const nullableRisk = (risk: unknown): McpToolRisk | null => {
    if (risk === null) return null
    if (typeof risk !== 'string' || !risks.includes(risk)) throw badResponse()
    return risk as McpToolRisk
  }
  const effective = nullableRisk(row.effective_risk)
  if (!effective) throw badResponse()
  return {
    tool_name: text(row.tool_name), description: text(row.description), enabled: flag(row.enabled),
    read_only_hint: flag(row.read_only_hint), catalog_status: text(row.catalog_status),
    catalog_error: row.catalog_error === null ? null : text(row.catalog_error),
    explicit_risk: nullableRisk(row.explicit_risk), observed_risk: nullableRisk(row.observed_risk), effective_risk: effective,
    require_approval: flag(row.require_approval), pending_downgrade: flag(row.pending_downgrade),
  }
}

function tenantPath(tenantId: string): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}`
}

function servicePath(tenantId: string, serviceId: string): string {
  return `${tenantPath(tenantId)}/mcp-services/${encodeURIComponent(serviceId)}`
}

/** Every service in this space, newest first. Requires active membership. */
export async function listMcpServices(tenantId: string): Promise<McpService[]> {
  const data: unknown = await get(`${tenantPath(tenantId)}/mcp-services`)
  if (!Array.isArray(data)) throw badResponse()
  return data.map(serviceFromResponse)
}

/** Create a service (`tools:manage`). */
export async function createMcpService(tenantId: string, body: McpServiceInput): Promise<McpService> {
  return serviceFromResponse(await post(`${tenantPath(tenantId)}/mcp-services`, body))
}

/** Update a service; changing the connection parameters invalidates its cached tools. */
export async function updateMcpService(
  tenantId: string,
  serviceId: string,
  body: McpServiceUpdateInput,
): Promise<McpService> {
  return serviceFromResponse(await patch(servicePath(tenantId, serviceId), body))
}

export async function deleteMcpService(tenantId: string, serviceId: string): Promise<void> {
  await del(servicePath(tenantId, serviceId))
}

/**
 * Connect to the service and refresh its cached catalog. New tools arrive disabled.
 *
 * The server's own discovery budget is 30 s (adjustable up to 300 s), so the HTTP timeout is
 * relaxed past the browser default; a slower server must not be reported as unreachable.
 */
export async function discoverMcpService(
  tenantId: string,
  serviceId: string,
  timeoutMs = 65_000,
): Promise<McpDiscoveryResult> {
  const result = record(await post(
    `${servicePath(tenantId, serviceId)}/discover`,
    {},
    { timeout: timeoutMs },
  ))
  return { service_id: text(result.service_id), tools: textList(result.tools), fingerprint: text(result.fingerprint) }
}

/** Cached tool catalog with enablement and effective risk. Requires active membership. */
export async function listMcpServiceTools(tenantId: string, serviceId: string): Promise<McpServiceTool[]> {
  const data: unknown = await get(`${servicePath(tenantId, serviceId)}/tools`)
  if (!Array.isArray(data)) throw badResponse()
  return data.map(toolFromResponse)
}

/** Replace the enable whitelist; only discovered tool names are accepted. Returns the stored names. */
export async function setEnabledMcpTools(
  tenantId: string,
  serviceId: string,
  tools: string[],
): Promise<string[]> {
  return textList(await put(`${servicePath(tenantId, serviceId)}/enabled-tools`, { tools }))
}
