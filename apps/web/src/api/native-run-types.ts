/**
 * Pure types and runtime guards for the Native Run API. No network, axios or i18n imports, so the
 * workbench state and its tests can use them directly. `api/native-runs.ts` re-exports everything here.
 */

export const RUN_STATUSES = [
  'queued',
  'running',
  'waiting_input',
  'waiting_approval',
  'completed',
  'failed',
  'cancelled',
  'interrupted',
] as const
export type RunStatus = (typeof RUN_STATUSES)[number]

export const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled', 'interrupted'])

export interface RunView {
  id: string
  tenant_id: string
  session_id: string
  principal_id: string
  status: RunStatus
  attempt: number
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  ended_at: string | null
  queue_position: number | null
  attention_required: boolean
}

export interface RunEvent {
  event_id: string
  run_id: string
  sequence: number
  event_type: string
  schema_version: number
  payload: Record<string, unknown>
  occurred_at: string
  /** Live-only text: not stored, `sequence` is just the last stored event before it. Dropped on `stream.resync`. */
  ephemeral?: boolean
}

export interface SessionView {
  id: string
  tenant_id: string
  owner_user_id: string
  agent_version_id: string
  runtime_type: string
  title: string
  status: string
  created_at: string
  updated_at: string
}

export interface AgentView {
  id: string
  name: string
  description: string
  status: string
  /** Version id to create Sessions against; null while the agent has never been published. */
  published_version_id: string | null
}

export interface ConversationMessage {
  id: string
  run_id: string | null
  sequence: number
  role: string
  content: string
  created_at: string
  /** Knowledge citations of an assistant answer; empty for other messages. */
  citations?: KnowledgeCitation[]
}

/** One resolved `[ID:n]` handle of an answer (openspec 2026-11-06-knowledge-base K1.8). */
export interface KnowledgeCitation {
  handle: number
  chunk_id: string
  kb_id?: string
  document_id?: string
  version_id?: string
  filename?: string
  page?: number | null
  section?: string[]
  ordinal?: number
}

export interface ConversationPage {
  messages: ConversationMessage[]
  latest_run: RunView | null
}

export interface PendingInput {
  input_request_id: string
  question: string
  candidates: string[]
}

type Unknown = Record<string, unknown>

export function isRecord(value: unknown): value is Unknown {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function isString(value: unknown): value is string {
  return typeof value === 'string'
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value)
}

/** True when `value` has the RunView shape the workbench relies on. */
export function isRunView(value: unknown): value is RunView {
  return isRecord(value)
    && isString(value.id) && isString(value.tenant_id) && isString(value.session_id)
    && isString(value.principal_id)
    && (RUN_STATUSES as readonly string[]).includes(value.status as string)
    && isInteger(value.attempt)
    && isNullableString(value.error_code) && isNullableString(value.error_message)
    && isString(value.created_at)
    && isNullableString(value.started_at) && isNullableString(value.ended_at)
    && (value.queue_position === null || isInteger(value.queue_position))
    && typeof value.attention_required === 'boolean'
}

/** True when `value` has the RunEvent shape. Payload contents are checked by the reducer per event type. */
export function isRunEvent(value: unknown): value is RunEvent {
  return isRecord(value)
    && isString(value.event_id) && isString(value.run_id)
    && isInteger(value.sequence) && value.sequence >= 1
    && isString(value.event_type)
    && isRecord(value.payload)
    && isString(value.occurred_at)
}

/** A tool the owner allowed for the rest of a session (openspec 2026-11-06-tool-call-hardening E). */
export interface ToolGrant {
  id: string
  tool_name: string
  risk: string
  created_at: string
}

/** Validate `GET .../tool-grants`; malformed items are dropped. */
export function toolGrantsFromResponse(data: unknown): ToolGrant[] {
  if (!Array.isArray(data)) throw new Error('Unexpected tool grant response')
  return data.filter(isRecord).filter(item => isString(item.id) && isString(item.tool_name)).map(item => ({
    id: item.id as string, tool_name: item.tool_name as string,
    risk: isString(item.risk) ? item.risk : 'write', created_at: isString(item.created_at) ? item.created_at : '',
  }))
}
