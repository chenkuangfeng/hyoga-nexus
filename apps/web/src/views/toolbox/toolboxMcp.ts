/**
 * Pure helpers of the toolbox MCP panel (openspec 2026-11-08-mcp, tasks 4.1–4.2).
 *
 * The dialog edits rows a human can read (newline-separated args, key/value rows), while the
 * server stores a normalized config whose header/env values are either literals or
 * `{"$credential_ref": "<id>"}` markers. Keeping the conversion here makes the rules testable
 * without mounting the component: secrets never gain a separate client-side store, and a
 * credential reference stays a reference — it is never flattened into the value it points at.
 */
import type {
  McpConnectionConfig,
  McpCredentialReference,
  McpService,
  McpServiceTool,
  McpTransport,
} from '@/api/nexus-mcp'

/** One editable header/env entry. `reference` switches the value to a credential reference id. */
export interface McpKeyValueRow {
  key: string
  value: string
  reference: boolean
}

/** Editable shape of the create/edit dialog, independent of the stored config. */
export interface McpServiceFormState {
  name: string
  description: string
  transport: McpTransport
  url: string
  command: string
  /** One argument per line; blank lines are dropped. */
  args: string
  timeout: number
  /** SSE only: how long one event may take before the stream counts as dead. */
  sseReadTimeout: number
  authType: 'none' | 'oauth'
  /** Space-separated, as OAuth scopes are conventionally written. */
  oauthScopes: string
  oauthClientId: string
  headers: McpKeyValueRow[]
  env: McpKeyValueRow[]
}

/** Which field blocked submission; the dialog maps it to a translated message. */
export type McpFormProblem = 'nameRequired' | 'urlRequired' | 'commandRequired'

export function isCredentialReference(value: unknown): value is McpCredentialReference {
  return (
    typeof value === 'object'
    && value !== null
    && Object.keys(value).length === 1
    && typeof (value as Record<string, unknown>).$credential_ref === 'string'
  )
}

/** Stored header/env entries as editable rows, preserving a reference instead of its secret. */
export function entriesToRows(entries?: Record<string, unknown>): McpKeyValueRow[] {
  return Object.entries(entries ?? {}).map(([key, value]) => {
    if (isCredentialReference(value)) return { key, value: value.$credential_ref, reference: true }
    return { key, value: typeof value === 'string' ? value : '', reference: false }
  })
}

/** Editable rows as a stored map; empty keys and values are dropped rather than sent blank. */
export function rowsToEntries(rows: readonly McpKeyValueRow[]): Record<string, string | McpCredentialReference> {
  const entries: Record<string, string | McpCredentialReference> = {}
  for (const row of rows) {
    const key = row.key.trim()
    const value = row.value.trim()
    if (!key || !value) continue
    entries[key] = row.reference ? { $credential_ref: value } : value
  }
  return entries
}

/** The dialog's starting state: the stored service, or sensible defaults for a new one. */
export function formFromService(service?: McpService | null): McpServiceFormState {
  const config = service?.config ?? {}
  return {
    name: service?.name ?? '',
    description: service?.description ?? '',
    transport: service?.transport ?? 'streamable_http',
    url: config.url ?? '',
    command: config.command ?? '',
    args: (config.args ?? []).join('\n'),
    timeout: config.timeout ?? 30,
    sseReadTimeout: config.sse_read_timeout ?? 300,
    authType: config.auth_type === 'oauth' ? 'oauth' : 'none',
    oauthScopes: (config.oauth?.scopes ?? []).join(' '),
    oauthClientId: config.oauth?.client_id ?? '',
    headers: entriesToRows(config.headers),
    env: entriesToRows(config.env),
  }
}

/**
 * Build the connection config for a create/update request.
 *
 * OAuth client secrets are never editable here: the stored secret and metadata URL are carried
 * over from `previous` so saving unrelated fields does not silently wipe the registration.
 */
export function configFromForm(form: McpServiceFormState, previous?: McpService | null): McpConnectionConfig {
  const config: McpConnectionConfig = {
    transport: form.transport,
    timeout: Number.isFinite(form.timeout) && form.timeout > 0 ? form.timeout : 30,
    // stdio has no HTTP authorization, so it must stay "none" even if the form kept an old choice.
    auth_type: form.transport === 'stdio' ? 'none' : form.authType,
  }
  if (form.transport === 'stdio') {
    config.command = form.command.trim()
    config.args = form.args.split(/\r?\n/).map((arg) => arg.trim()).filter(Boolean)
    config.env = rowsToEntries(form.env)
    return config
  }
  config.url = form.url.trim()
  config.headers = rowsToEntries(form.headers)
  if (form.transport === 'sse') {
    config.sse_read_timeout = Number.isFinite(form.sseReadTimeout) && form.sseReadTimeout > 0
      ? form.sseReadTimeout
      : 300
  }
  if (form.authType === 'oauth') {
    const stored = previous?.config.oauth
    config.oauth = {
      scopes: form.oauthScopes.split(/\s+/).map((scope) => scope.trim()).filter(Boolean),
      client_id: form.oauthClientId.trim() || null,
      client_secret: stored?.client_secret ?? null,
      auth_server_metadata_url: stored?.auth_server_metadata_url ?? null,
    }
  }
  return config
}

/** The first blocking problem, or `null` when the form can be submitted. */
export function validateMcpForm(form: McpServiceFormState): McpFormProblem | null {
  if (!form.name.trim()) return 'nameRequired'
  if (form.transport === 'stdio') return form.command.trim() ? null : 'commandRequired'
  const url = form.url.trim().toLowerCase()
  return url.startsWith('http://') || url.startsWith('https://') ? null : 'urlRequired'
}

/** A one-line connection target for the service row: the URL, or the stdio command with its args. */
export function serviceTarget(service: McpService): string {
  if (service.transport !== 'stdio') return service.config.url ?? ''
  return [service.config.command ?? '', ...(service.config.args ?? [])].join(' ').trim()
}

/** The enabled whitelist in catalog order, as the enablement endpoint expects it. */
export function enabledToolNames(tools: readonly McpServiceTool[]): string[] {
  return tools.filter((tool) => tool.enabled).map((tool) => tool.tool_name)
}
