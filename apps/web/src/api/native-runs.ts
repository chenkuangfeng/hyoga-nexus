/**
 * Platform Native Run API client (apps/api `/api/v1/tenants/{tenant_id}/...`).
 *
 * Every function takes the tenant (space) id explicitly, because the platform scopes Runs by tenant
 * in the path. Authentication, the active-space header and error handling come from `utils/request`.
 * Responses are validated at runtime before use: a type assertion alone would accept malformed data.
 *
 * The event stream is the one exception to the axios helpers: it is a long-lived SSE response, so it
 * uses `@microsoft/fetch-event-source` with the same auth headers.
 */
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { get, post } from '@/utils/request'
import { getApiBaseUrl } from '@/utils/api-base'
import {
  isRecord,
  isRunEvent,
  isRunView,
  isString,
  type ConversationMessage,
  type ConversationPage,
  type AgentView,
  type PendingInput,
  type RunEvent,
  type RunView,
  type SessionView,
} from './native-run-types'

export * from './native-run-types'

function requireValid<T>(value: unknown, guard: (v: unknown) => v is T, label: string): T {
  if (!guard(value)) {
    throw new Error(`Unexpected ${label} response`)
  }
  return value
}

function tenantPath(tenantId: string): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}`
}

export async function listAgents(tenantId: string): Promise<AgentView[]> {
  const data: unknown = await get(`${tenantPath(tenantId)}/agents`)
  if (!Array.isArray(data)) throw new Error('Unexpected agent list response')
  return data as AgentView[]
}

export async function listSessions(tenantId: string): Promise<SessionView[]> {
  const data: unknown = await get(`${tenantPath(tenantId)}/sessions`)
  if (!Array.isArray(data)) throw new Error('Unexpected session list response')
  return data as SessionView[]
}

export async function createSession(tenantId: string, agentVersionId: string, title: string): Promise<SessionView> {
  return post<SessionView>(`${tenantPath(tenantId)}/sessions`, { agent_version_id: agentVersionId, title })
}

export async function getConversation(tenantId: string, sessionId: string): Promise<ConversationPage> {
  const data: unknown = await get(`${tenantPath(tenantId)}/sessions/${encodeURIComponent(sessionId)}/messages`)
  if (!isRecord(data) || !Array.isArray(data.messages)) throw new Error('Unexpected conversation response')
  const latest = data.latest_run === null ? null : requireValid(data.latest_run, isRunView, 'run')
  return { messages: data.messages as ConversationMessage[], latest_run: latest }
}

/**
 * Submit one message as a new Run. `idempotencyKey` must be stable across retries of the same user action,
 * so a retried submit replays the original Run instead of starting a second one.
 */
export async function submitRun(tenantId: string, sessionId: string, message: string, idempotencyKey: string): Promise<RunView> {
  const data = await post<unknown>(`${tenantPath(tenantId)}/sessions/${encodeURIComponent(sessionId)}/runs`,
    { message }, { headers: { 'Idempotency-Key': idempotencyKey } })
  return requireValid(data, isRunView, 'run')
}

export async function getRun(tenantId: string, runId: string): Promise<RunView> {
  const data: unknown = await get(`${tenantPath(tenantId)}/runs/${encodeURIComponent(runId)}`)
  return requireValid(data, isRunView, 'run')
}

export async function getPendingInput(tenantId: string, runId: string): Promise<PendingInput | null> {
  const data: unknown = await get(`${tenantPath(tenantId)}/runs/${encodeURIComponent(runId)}/input`)
  if (data === null || data === undefined) return null
  if (!isRecord(data) || !isString(data.input_request_id) || !isString(data.question)) {
    throw new Error('Unexpected pending input response')
  }
  const candidates = Array.isArray(data.candidates) ? data.candidates.filter(isString) : []
  return { input_request_id: data.input_request_id, question: data.question, candidates }
}

export async function submitInput(tenantId: string, runId: string, inputRequestId: string, response: string,
  idempotencyKey: string): Promise<RunView> {
  const data = await post<unknown>(`${tenantPath(tenantId)}/runs/${encodeURIComponent(runId)}/input`,
    { input_request_id: inputRequestId, response }, { headers: { 'Idempotency-Key': idempotencyKey } })
  return requireValid(data, isRunView, 'run')
}

export async function cancelRun(tenantId: string, runId: string): Promise<RunView> {
  const data = await post<unknown>(`${tenantPath(tenantId)}/runs/${encodeURIComponent(runId)}/cancel`, {})
  return requireValid(data, isRunView, 'run')
}

/** Page size of `GET .../runs/{id}/events` (server maximum). */
const EVENT_PAGE_LIMIT = 500

/**
 * Read every persisted event of one Run, in sequence order. Used to rebuild the timeline of
 * finished answers; pages until a short page. Malformed rows are dropped.
 */
export async function listRunEvents(tenantId: string, runId: string): Promise<RunEvent[]> {
  const events: RunEvent[] = []
  let after = 0
  for (;;) {
    const data: unknown = await get(`${tenantPath(tenantId)}/runs/${encodeURIComponent(runId)}/events`,
      { params: { after_sequence: after, limit: EVENT_PAGE_LIMIT } })
    if (!Array.isArray(data)) throw new Error('Unexpected run events response')
    const page = data.filter(isRunEvent)
    events.push(...page)
    if (data.length < EVENT_PAGE_LIMIT || page.length === 0) return events
    after = page[page.length - 1].sequence
  }
}

/** A pending tool approval of the caller's own Run; arguments are only exposed here, never in events. */
export interface PendingApproval {
  id: string
  tool_name: string
  arguments: Record<string, unknown>
}

export async function listPendingApprovals(tenantId: string, runId: string): Promise<PendingApproval[]> {
  const data: unknown = await get(`${tenantPath(tenantId)}/native/runs/${encodeURIComponent(runId)}/approvals`)
  if (!Array.isArray(data)) throw new Error('Unexpected approvals response')
  return data.filter((row): row is PendingApproval => isRecord(row) && isString(row.id) && isString(row.tool_name))
    .map(row => ({ ...row, arguments: isRecord(row.arguments) ? row.arguments : {} }))
}

/** Approve or reject one tool call; approval may carry corrected arguments (revalidated by the server). */
export async function resolveApproval(tenantId: string, runId: string, approvalId: string, approve: boolean,
  args?: Record<string, unknown>): Promise<void> {
  await post(`${tenantPath(tenantId)}/native/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
    { approve, arguments: approve ? args ?? null : null })
}

/** "Keep waiting" on a watchdog alert. Does not change the Run's execution. */
export async function acknowledgeWatchdog(tenantId: string, runId: string): Promise<RunView> {
  const data = await post<unknown>(`${tenantPath(tenantId)}/runs/${encodeURIComponent(runId)}/watchdog/acknowledge`, {})
  return requireValid(data, isRunView, 'run')
}

/** Queue a correction for a running Run; it is injected at the next round boundary and never starts a new Run. */
export async function steerRun(tenantId: string, runId: string, content: string, idempotencyKey: string): Promise<void> {
  await post(`/api/v1/tenants/${encodeURIComponent(tenantId)}/native/runs/${encodeURIComponent(runId)}/steer`,
    { content }, { headers: { 'Idempotency-Key': idempotencyKey } })
}

/** Headers the axios interceptor adds, repeated for the SSE request which bypasses axios. */
function streamHeaders(): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'text/event-stream' }
  const token = localStorage.getItem('weknora_token')
  if (token) headers.Authorization = `Bearer ${token}`
  const selectedTenant = localStorage.getItem('weknora_selected_tenant_id')
  if (selectedTenant) headers['X-Tenant-ID'] = selectedTenant
  return headers
}

export interface RunEventStreamOptions {
  /** Last sequence the caller already holds; the server replays events after it. */
  afterSequence: number
  signal: AbortSignal
  onEvent: (event: RunEvent) => void
  /** Called when the server ends the stream (Run terminal or waiting for input/approval). */
  onEnd: () => void
}

/**
 * Subscribe to `run.event` messages from `afterSequence`. Resolves when the stream ends or `signal` aborts.
 * Malformed messages are dropped rather than rendered. Network errors reject so the caller can show them.
 */
export async function streamRunEvents(tenantId: string, runId: string, options: RunEventStreamOptions): Promise<void> {
  const url = `${getApiBaseUrl()}${tenantPath(tenantId)}/runs/${encodeURIComponent(runId)}/events`
  await fetchEventSource(url, {
    method: 'GET',
    headers: { ...streamHeaders(), 'Last-Event-ID': String(options.afterSequence) },
    signal: options.signal,
    openWhenHidden: true,
    onmessage(message) {
      if (message.event !== 'run.event' || !message.data) return
      let parsed: unknown
      try {
        parsed = JSON.parse(message.data)
      } catch {
        return
      }
      if (isRunEvent(parsed)) options.onEvent(parsed)
    },
    onclose() {
      // A normal close ends the library's loop without retrying; only errors trigger retries.
      options.onEnd()
    },
    onerror(error) {
      // Rethrow to stop automatic retries: the caller decides whether to reconnect.
      throw error
    },
  })
}
