import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { RunEvent, RunView } from '../../api/native-run-types'
import {
  appendEvent,
  assistantSegments,
  canCancel,
  canSteer,
  changesRunView,
  dropEphemeral,
  emptyRunState,
  failureCode,
  isTerminal,
  needsInput,
  showWatchdogBanner,
  toolCalls,
} from './nativeRunState'

function run(overrides: Partial<RunView> = {}): RunView {
  return {
    id: 'run-1',
    tenant_id: 'tenant-1',
    session_id: 'session-1',
    principal_id: 'user-1',
    status: 'running',
    attempt: 1,
    error_code: null,
    error_message: null,
    created_at: '2026-11-04T00:00:00Z',
    started_at: null,
    ended_at: null,
    queue_position: null,
    attention_required: false,
    ...overrides,
  }
}

function event(sequence: number, eventType: string, payload: Record<string, unknown> = {}): RunEvent {
  return {
    event_id: `e${sequence}`,
    run_id: 'run-1',
    sequence,
    event_type: eventType,
    schema_version: 1,
    payload,
    occurred_at: '2026-11-04T00:00:00Z',
  }
}

test('appendEvent keeps one copy per sequence and ignores replays after a reconnect', () => {
  let state = emptyRunState(run())
  state = appendEvent(state, event(1, 'run.started'))
  state = appendEvent(state, event(2, 'message.delta', { text: 'Hi', turn: 1 }))
  const replayed = appendEvent(state, event(2, 'message.delta', { text: 'Hi', turn: 1 }))
  assert.equal(replayed, state)
  assert.deepEqual(replayed.events.map(e => e.sequence), [1, 2])
  assert.equal(replayed.lastSequence, 2)
})

test('appendEvent ignores an older sequence that arrives late', () => {
  let state = emptyRunState()
  state = appendEvent(state, event(5, 'tool.started', { invocation_id: 'a' }))
  state = appendEvent(state, event(3, 'tool.started', { invocation_id: 'b' }))
  assert.deepEqual(state.events.map(e => e.sequence), [5])
})

test('assistant text joins deltas per turn in order and separates turns', () => {
  const events = [
    event(1, 'message.delta', { text: 'Hel', turn: 1 }),
    event(2, 'message.delta', { text: 'lo', turn: 1 }),
    event(3, 'tool.started', { invocation_id: 'x', name: 'echo' }),
    event(4, 'message.delta', { text: 'World', turn: 2 }),
    event(5, 'message.delta', { turn: 2 }),
  ]
  assert.deepEqual(assistantSegments(events), [{ turn: 1, text: 'Hello' }, { turn: 2, text: 'World' }])
})

test('tool calls update in place when their completion arrives', () => {
  const events = [
    event(1, 'tool.started', { invocation_id: 'a', name: 'search', signature: 'search:x' }),
    event(2, 'tool.started', { invocation_id: 'b', name: 'fetch' }),
    event(3, 'tool.completed', { invocation_id: 'a', status: 'completed', summary: 'ok', error_code: null }),
    event(4, 'tool.failed', { invocation_id: 'b', status: 'failed', summary: '', error_code: 'tool_timeout' }),
  ]
  assert.deepEqual(toolCalls(events), [
    { invocationId: 'a', name: 'search', status: 'completed', summary: 'ok', errorCode: null },
    { invocationId: 'b', name: 'fetch', status: 'failed', summary: '', errorCode: 'tool_timeout' },
  ])
})

test('watchdog banner shows only for unfinished Runs the server flags', () => {
  assert.equal(showWatchdogBanner(run({ attention_required: true })), true)
  assert.equal(showWatchdogBanner(run({ attention_required: false })), false)
  assert.equal(showWatchdogBanner(run({ attention_required: true, status: 'cancelled' })), false)
  assert.equal(showWatchdogBanner(null), false)
})

test('actions follow the Run status', () => {
  assert.equal(canCancel(run({ status: 'running' })), true)
  assert.equal(canCancel(run({ status: 'waiting_input' })), true)
  assert.equal(canCancel(run({ status: 'completed' })), false)
  assert.equal(canSteer(run({ status: 'running' })), true)
  assert.equal(canSteer(run({ status: 'queued' })), false)
  assert.equal(needsInput(run({ status: 'waiting_input' })), true)
  assert.equal(needsInput(run({ status: 'running' })), false)
  assert.equal(isTerminal(run({ status: 'interrupted' })), true)
})

test('only Run-changing events trigger a Run refresh', () => {
  assert.equal(changesRunView(event(1, 'message.delta', { text: 'a' })), false)
  assert.equal(changesRunView(event(2, 'tool.progress', { text: 'a' })), false)
  assert.equal(changesRunView(event(3, 'run.watchdog_alert', { rule: 'idle' })), true)
  assert.equal(changesRunView(event(4, 'input.requested', {})), true)
})

test('failure codes are exposed only for failed or interrupted Runs', () => {
  assert.equal(failureCode(run({ status: 'failed', error_code: 'model_timeout', error_message: 'secret detail' })), 'model_timeout')
  assert.equal(failureCode(run({ status: 'completed', error_code: null })), null)
  assert.equal(failureCode(null), null)
})

test('live-only text is kept in arrival order, never moves the resume cursor, and is dropped on resync', () => {
  const stored = (sequence: number, event_type: string, payload: Record<string, unknown> = {}): RunEvent =>
    ({ event_id: `s${sequence}`, run_id: 'run-1', sequence, event_type, schema_version: 1, payload, occurred_at: '' })
  let state = emptyRunState(run())
  state = appendEvent(state, stored(4, 'run.started'))
  // Same sequence as the last stored event, yet it must not be taken for a replay.
  state = appendEvent(state, { ...stored(4, 'message.delta', { text: '你', turn: 1 }), ephemeral: true })
  state = appendEvent(state, { ...stored(4, 'message.delta', { text: '好', turn: 1 }), ephemeral: true })
  assert.equal(state.events.length, 3)
  assert.equal(state.lastSequence, 4)
  assert.deepEqual(assistantSegments(state.events), [{ turn: 1, text: '你好' }])
  state = dropEphemeral(state)
  assert.deepEqual(state.events.map(event => event.event_type), ['run.started'])
  assert.equal(state.lastSequence, 4)
  // The stored whole text then supplies the answer.
  state = appendEvent(state, stored(5, 'message.completed', { turn: 1, text: '你好吗' }))
  assert.deepEqual(assistantSegments(state.events), [{ turn: 1, text: '你好吗' }])
})
