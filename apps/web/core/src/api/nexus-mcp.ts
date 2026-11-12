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

function tenantPath(tenantId: string): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}`
}

function servicePath(tenantId: string, serviceId: string): string {
  return `${tenantPath(tenantId)}/mcp-services/${encodeURIComponent(serviceId)}`
}

/** Every service in this space, newest first. Requires active membership. */
export async function listMcpServices(tenantId: string): Promise<McpService[]> {
  const data = await get<McpService[]>(`${tenantPath(tenantId)}/mcp-services`)
  return Array.isArray(data) ? data : []
}

/** Create a service (`tools:manage`). */
export async function createMcpService(tenantId: string, body: McpServiceInput): Promise<McpService> {
  return await post<McpService>(`${tenantPath(tenantId)}/mcp-services`, body)
}

/** Update a service; changing the connection parameters invalidates its cached tools. */
export async function updateMcpService(
  tenantId: string,
  serviceId: string,
  body: McpServiceUpdateInput,
): Promise<McpService> {
  return await patch<McpService>(servicePath(tenantId, serviceId), body)
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
  return await post<McpDiscoveryResult>(
    `${servicePath(tenantId, serviceId)}/discover`,
    {},
    { timeout: timeoutMs },
  )
}

/** Cached tool catalog with enablement and effective risk. Requires active membership. */
export async function listMcpServiceTools(tenantId: string, serviceId: string): Promise<McpServiceTool[]> {
  const data = await get<McpServiceTool[]>(`${servicePath(tenantId, serviceId)}/tools`)
  return Array.isArray(data) ? data : []
}

/** Replace the enable whitelist; only discovered tool names are accepted. Returns the stored names. */
export async function setEnabledMcpTools(
  tenantId: string,
  serviceId: string,
  tools: string[],
): Promise<string[]> {
  const data = await put<string[]>(`${servicePath(tenantId, serviceId)}/enabled-tools`, { tools })
  return Array.isArray(data) ? data : []
}
