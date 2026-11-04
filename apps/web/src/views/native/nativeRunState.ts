/**
 * Pure state for one Native Run as shown in the workbench. No Vue or network imports, so the rules
 * (dedupe, ordering, what each status allows) are testable directly.
 *
 * The server is the source of truth. Events are an append-only log, the Run view carries the status
 * and `attention_required`, and this module only derives what to display from them.
 */
import { TERMINAL_RUN_STATUSES, type RunEvent, type RunView } from '../../api/native-run-types'

export interface RunState {
  run: RunView | null
  /** Unique by sequence, ascending. */
  events: RunEvent[]
  lastSequence: number
}

export interface ToolCallItem {
  invocationId: string
  name: string
  /** `running` until a completed or failed event arrives for the same invocation. */
  status: 'running' | 'completed' | 'failed'
  summary: string
  errorCode: string | null
}

export interface TextSegment {
  turn: number
  text: string
}

export function emptyRunState(run: RunView | null = null): RunState {
  return { run, events: [], lastSequence: 0 }
}

/**
 * Add one event if it is new. Replays and duplicates (same or lower sequence) are ignored, so an
 * event delivered twice across a reconnect never renders twice.
 */
export function appendEvent(state: RunState, event: RunEvent): RunState {
  if (event.sequence <= state.lastSequence) return state
  return { ...state, events: [...state.events, event], lastSequence: event.sequence }
}

export function withRun(state: RunState, run: RunView): RunState {
  return { ...state, run }
}

/** Streamed model text grouped by turn. Each turn's deltas are joined in sequence order. */
export function assistantSegments(events: readonly RunEvent[]): TextSegment[] {
  const segments: TextSegment[] = []
  for (const event of events) {
    if (event.event_type !== 'message.delta') continue
    const text = event.payload.text
    if (typeof text !== 'string') continue
    const turn = typeof event.payload.turn === 'number' ? event.payload.turn : 0
    const last = segments[segments.length - 1]
    if (last && last.turn === turn) {
      last.text += text
    } else {
      segments.push({ turn, text })
    }
  }
  return segments
}

/** Tool calls in first-seen order, updated by their completed or failed events. */
export function toolCalls(events: readonly RunEvent[]): ToolCallItem[] {
  const byId = new Map<string, ToolCallItem>()
  for (const event of events) {
    const payload = event.payload
    const invocationId = typeof payload.invocation_id === 'string' ? payload.invocation_id : null
    if (!invocationId) continue
    if (event.event_type === 'tool.started') {
      if (!byId.has(invocationId)) {
        byId.set(invocationId, {
          invocationId,
          name: typeof payload.name === 'string' ? payload.name : 'tool',
          status: 'running',
          summary: '',
          errorCode: null,
        })
      }
    } else if (event.event_type === 'tool.completed' || event.event_type === 'tool.failed') {
      const item = byId.get(invocationId)
      if (item) {
        item.status = event.event_type === 'tool.completed' ? 'completed' : 'failed'
        item.summary = typeof payload.summary === 'string' ? payload.summary : ''
        item.errorCode = typeof payload.error_code === 'string' ? payload.error_code : null
      }
    }
  }
  return [...byId.values()]
}

/** Terminal Runs never show watchdog or input affordances, whatever the last event says. */
export function isTerminal(run: RunView | null): boolean {
  return run !== null && TERMINAL_RUN_STATUSES.has(run.status)
}

/** Whether the Run still needs the stream open: queued or actively executing. */
export function isActive(run: RunView | null): boolean {
  return run !== null && (run.status === 'queued' || run.status === 'running')
}

/** The watchdog banner: only while the server reports attention and the Run has not ended. */
export function showWatchdogBanner(run: RunView | null): boolean {
  return run !== null && run.attention_required && !isTerminal(run)
}

/** Cancel is offered for every non-terminal Run; the server decides how a running Run stops. */
export function canCancel(run: RunView | null): boolean {
  return run !== null && !isTerminal(run)
}

/** Corrections are injected into a running Run only. A queued Run has not started, so it cannot take them. */
export function canSteer(run: RunView | null): boolean {
  return run !== null && run.status === 'running'
}

/** Input is answered only when the Run is waiting for it. The question itself comes from the input endpoint. */
export function needsInput(run: RunView | null): boolean {
  return run !== null && run.status === 'waiting_input'
}

/**
 * Events that can change the Run view (status, attention, input). Text and tool progress do not, so
 * they do not trigger a Run refresh.
 */
export function changesRunView(event: RunEvent): boolean {
  return event.event_type !== 'message.delta' && event.event_type !== 'tool.progress'
}

/** Error code for a failed or interrupted Run. The free-text error message is not displayed: it may contain internals. */
export function failureCode(run: RunView | null): string | null {
  if (!run || !(run.status === 'failed' || run.status === 'interrupted')) return null
  return run.error_code
}
