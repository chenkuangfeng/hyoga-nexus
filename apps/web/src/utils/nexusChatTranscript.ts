/**
 * Build the WeKnora chat rows (`usermsg` / `botmsg` inputs) from Nexus conversation messages and Run events.
 *
 * WeKnora renders one assistant row per answer, with the whole agent timeline (`agentEventStream`).
 * Nexus persists one message per model or tool step, all tagged with the Run that produced them.
 * Rows are therefore grouped by Run: each user message is followed by one assistant row for its Run,
 * whose timeline comes from that Run's events (`GET .../runs/{id}/events`). Without events (still
 * loading, or the read failed) the row falls back to the persisted answer text, rendered as Markdown.
 *
 * Pure module (no Vue, no network) so the grouping rules are unit tested.
 */
import { TERMINAL_RUN_STATUSES, type ConversationMessage, type RunEvent } from '../api/native-run-types'
import { toAgentEventStream, type AgentEventStreamOptions, type AgentStreamEvent } from './nexusAgentEvents'

export interface ChatUserRow {
  role: 'user'
  id: string
  content: string
  created_at: string
}

/** Fields read by WeKnora `botmsg`, `AgentStreamDisplay` and the prompt dock. */
export interface ChatAssistantRow {
  role: 'assistant'
  /** Stable key: the Run id (one row per Run). */
  id: string
  run_id: string | null
  assistant_message_id: string
  request_id: string
  content: string
  created_at: string
  isAgentMode: boolean
  agentEventStream: AgentStreamEvent[]
  knowledge_references: []
  /** False only for the Run still streaming or waiting; settled rows are history. */
  is_completed: boolean
  /** Status used to close the timeline (terminal Runs close open answers and cards). */
  run_status: string
}

export type ChatRow = ChatUserRow | ChatAssistantRow

export interface LiveRun {
  id: string
  status: string
  events: readonly RunEvent[]
  options?: AgentEventStreamOptions
}

/** Status of a finished Run from its terminal `run.<status>` event; `completed` when none is recorded. */
export function statusFromEvents(events: readonly RunEvent[]): string {
  for (let i = events.length - 1; i >= 0; i--) {
    const type = events[i].event_type
    if (type.startsWith('run.')) {
      const status = type.slice(4)
      if (TERMINAL_RUN_STATUSES.has(status)) return status
    }
  }
  return 'completed'
}

function assistantRow(runId: string | null, key: string, content: string, createdAt: string,
  events: readonly RunEvent[] | undefined, status: string, live: boolean, options?: AgentEventStreamOptions): ChatAssistantRow {
  const stream = events ? toAgentEventStream(events, status, options) : []
  return {
    role: 'assistant',
    id: key,
    run_id: runId,
    assistant_message_id: key,
    request_id: runId ?? key,
    content,
    created_at: createdAt,
    isAgentMode: stream.length > 0,
    agentEventStream: stream,
    knowledge_references: [],
    is_completed: !live,
    run_status: status,
  }
}

/**
 * Group persisted messages into rows, then append not-yet-persisted user inputs and the live Run.
 *
 * - `user` messages become user rows; runtime-injected notes (role `system`) and `tool` rows are not
 *   shown on their own: tool exchanges are part of the timeline.
 * - Consecutive non-user messages of the same Run form one assistant row; its text is the Run's
 *   assistant messages joined, used when no timeline is available.
 * - The live Run, when not yet persisted, is appended after `pendingUsers`.
 */
export function buildChatRows(messages: readonly ConversationMessage[],
  eventsByRun: ReadonlyMap<string, readonly RunEvent[]>, pendingUsers: readonly string[] = [],
  live: LiveRun | null = null, baseOptions: AgentEventStreamOptions = {}): ChatRow[] {
  const rows: ChatRow[] = []
  let group: { runId: string | null; key: string; texts: string[]; createdAt: string } | null = null

  const flush = () => {
    if (!group) return
    const isLive = live !== null && group.runId === live.id
    const events = isLive ? live!.events : group.runId ? eventsByRun.get(group.runId) : undefined
    const status = isLive ? live!.status : events ? statusFromEvents(events) : 'completed'
    const content = group.texts.join('\n\n')
    if (content || (events && events.length > 0)) {
      rows.push(assistantRow(group.runId, group.key, content, group.createdAt, events, status,
        isLive && !TERMINAL_RUN_STATUSES.has(status), { ...baseOptions, ...(isLive ? live!.options : {}) }))
    }
    group = null
  }

  for (const message of messages) {
    if (message.role === 'user') {
      flush()
      rows.push({ role: 'user', id: message.id, content: message.content, created_at: message.created_at })
      continue
    }
    if (message.role !== 'assistant' && message.role !== 'tool') continue
    const key = message.run_id ?? message.id
    if (!group || group.key !== key) {
      flush()
      group = { runId: message.run_id, key, texts: [], createdAt: message.created_at }
    }
    if (message.role === 'assistant' && message.content.trim()) group.texts.push(message.content)
  }
  flush()

  pendingUsers.forEach((text, index) => {
    rows.push({ role: 'user', id: `pending-${index}`, content: text, created_at: '' })
  })

  const persisted = live !== null && rows.some(row => row.role === 'assistant' && row.run_id === live.id)
  if (live && !persisted && (live.events.length > 0 || !TERMINAL_RUN_STATUSES.has(live.status))) {
    const row = assistantRow(live.id, live.id, '', '', live.events, live.status,
      !TERMINAL_RUN_STATUSES.has(live.status), { ...baseOptions, ...live.options })
    if (row.agentEventStream.length > 0) rows.push(row)
  }
  return rows
}

/** Runs whose events are needed to rebuild finished answers (excluding the live Run). */
export function runsNeedingEvents(messages: readonly ConversationMessage[], loaded: ReadonlySet<string>,
  liveRunId: string | null): string[] {
  const ids: string[] = []
  for (const message of messages) {
    const id = message.run_id
    if (id && id !== liveRunId && !loaded.has(id) && !ids.includes(id)) ids.push(id)
  }
  return ids
}

/** Plain-text transcript for "copy as Markdown" (WeKnora ChatHeader menu). */
export function transcriptMarkdown(title: string, rows: readonly ChatRow[], labels: { user: string; assistant: string }): string {
  const parts = [`# ${title}`]
  for (const row of rows) {
    const text = row.role === 'assistant'
      ? (row.content || row.agentEventStream.filter(e => e.type === 'answer').map(e => (e as { content: string }).content).join('\n\n'))
      : row.content
    if (!text.trim()) continue
    parts.push(`## ${row.role === 'user' ? labels.user : labels.assistant}\n\n${text.trim()}`)
  }
  return parts.join('\n\n') + '\n'
}
