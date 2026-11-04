/**
 * Orchestrates one Native Run in the workbench: submit, follow the event stream, refresh the Run view,
 * and perform the actions the server allows. Derived display rules live in `views/native/nativeRunState`.
 *
 * Reconnects resume from the last sequence held, so a dropped connection never replays or duplicates
 * output, and never submits the Run again.
 */
import { ref, shallowRef } from 'vue'
import {
  acknowledgeWatchdog,
  cancelRun,
  getConversation,
  getPendingInput,
  getRun,
  streamRunEvents,
  steerRun,
  submitInput,
  submitRun,
  type ConversationMessage,
  type PendingInput,
  type RunView,
} from '@/api/native-runs'
import {
  appendEvent,
  changesRunView,
  emptyRunState,
  isActive,
  needsInput,
  withRun,
  type RunState,
} from '@/views/native/nativeRunState'

/** Pause before reopening the stream while a Run is still active but the server closed the response. */
const RECONNECT_DELAY_MS = 500

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export function useNativeRun(getTenantId: () => string | null) {
  const state = shallowRef<RunState>(emptyRunState())
  const pendingInput = ref<PendingInput | null>(null)
  const streamError = ref<string | null>(null)
  const submitting = ref(false)
  let controller: AbortController | null = null

  function requireTenant(): string {
    const tenantId = getTenantId()
    if (!tenantId) throw new Error('No active space selected')
    return tenantId
  }

  function stopStream() {
    controller?.abort()
    controller = null
  }

  function applyRun(run: RunView) {
    state.value = withRun(state.value, run)
  }

  async function refreshRun(tenantId: string, runId: string) {
    const run = await getRun(tenantId, runId)
    if (state.value.run?.id === runId) applyRun(run)
  }

  async function refreshPendingInput(tenantId: string, runId: string) {
    pendingInput.value = await getPendingInput(tenantId, runId)
  }

  function handleEvent(tenantId: string, runId: string, event: Parameters<typeof appendEvent>[1]) {
    state.value = appendEvent(state.value, event)
    if (event.event_type === 'input.requested') {
      refreshPendingInput(tenantId, runId).catch(() => { pendingInput.value = null })
    }
    if (changesRunView(event)) {
      refreshRun(tenantId, runId).catch(() => { /* a failed refresh keeps the last known view */ })
    }
  }

  /**
   * Follow the Run's events until it ends. Each pass resumes after the last sequence held. The loop
   * stops when the Run is no longer active, or when the stream is aborted by a newer action.
   */
  async function follow(tenantId: string, runId: string, signal: AbortSignal) {
    streamError.value = null
    while (!signal.aborted) {
      try {
        await streamRunEvents(tenantId, runId, {
          afterSequence: state.value.lastSequence,
          signal,
          onEvent: event => handleEvent(tenantId, runId, event),
          onEnd: () => { /* handled after the loop body */ },
        })
      } catch (error) {
        if (signal.aborted) return
        streamError.value = error instanceof Error ? error.message : String(error)
        return
      }
      if (signal.aborted) return
      await refreshRun(tenantId, runId)
      if (needsInput(state.value.run)) {
        await refreshPendingInput(tenantId, runId)
        return
      }
      if (!isActive(state.value.run)) return
      await sleep(RECONNECT_DELAY_MS)
    }
  }

  function startFollowing(tenantId: string, runId: string) {
    stopStream()
    const next = new AbortController()
    controller = next
    void follow(tenantId, runId, next.signal)
  }

  /**
   * Load a session's latest Run. An unfinished Run is followed from sequence 1, which rebuilds its
   * events from the log. Returns the persisted messages for the transcript.
   */
  async function loadSession(sessionId: string): Promise<ConversationMessage[]> {
    const tenantId = requireTenant()
    stopStream()
    pendingInput.value = null
    const page = await getConversation(tenantId, sessionId)
    const latest = page.latest_run
    state.value = emptyRunState(latest)
    if (latest && isActive(latest)) {
      startFollowing(tenantId, latest.id)
    } else if (latest && needsInput(latest)) {
      await refreshPendingInput(tenantId, latest.id)
    }
    return page.messages
  }

  async function send(sessionId: string, message: string): Promise<void> {
    const tenantId = requireTenant()
    submitting.value = true
    try {
      const run = await submitRun(tenantId, sessionId, message, newIdempotencyKey())
      stopStream()
      pendingInput.value = null
      state.value = emptyRunState(run)
      startFollowing(tenantId, run.id)
    } finally {
      submitting.value = false
    }
  }

  async function acknowledge(): Promise<void> {
    const run = state.value.run
    if (!run) return
    applyRun(await acknowledgeWatchdog(requireTenant(), run.id))
  }

  async function cancel(): Promise<void> {
    const run = state.value.run
    if (!run) return
    const tenantId = requireTenant()
    applyRun(await cancelRun(tenantId, run.id))
    startFollowing(tenantId, run.id)
  }

  /** Queue a correction for a running Run. The text is delivered at the next round boundary. */
  async function steer(content: string): Promise<void> {
    const run = state.value.run
    if (!run) return
    await steerRun(requireTenant(), run.id, content, newIdempotencyKey())
  }

  /** Answer the question the Run is waiting for, then follow it again. */
  async function answerInput(response: string): Promise<void> {
    const run = state.value.run
    const request = pendingInput.value
    if (!run || !request) return
    const tenantId = requireTenant()
    const updated = await submitInput(tenantId, run.id, request.input_request_id, response, newIdempotencyKey())
    pendingInput.value = null
    applyRun(updated)
    startFollowing(tenantId, run.id)
  }

  function dispose() {
    stopStream()
  }

  return {
    state,
    pendingInput,
    streamError,
    submitting,
    loadSession,
    send,
    acknowledge,
    cancel,
    steer,
    answerInput,
    dispose,
  }
}
