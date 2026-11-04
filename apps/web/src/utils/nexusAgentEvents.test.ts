import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { RunEvent } from '../api/native-run-types.ts'
import { toAgentEventStream } from './nexusAgentEvents.ts'

let seq = 0
function ev(event_type: string, payload: Record<string, unknown> = {}): RunEvent {
  seq += 1
  return { event_id: `e${seq}`, run_id: 'run-1', sequence: seq, event_type, schema_version: 1, payload, occurred_at: '' }
}

test('text deltas of one turn merge into a single open answer', () => {
  const stream = toAgentEventStream([
    ev('message.delta', { text: '你', turn: 0 }),
    ev('message.delta', { text: '好', turn: 0 }),
  ], 'running')
  assert.equal(stream.length, 1)
  assert.deepEqual(stream[0], { ...stream[0], type: 'answer', content: '你好', done: false })
})

test('a tool event closes the answer and adds a pending tool call', () => {
  const stream = toAgentEventStream([
    ev('message.delta', { text: '查一下', turn: 0 }),
    ev('tool.started', { invocation_id: 'c1', name: 'search' }),
  ], 'running')
  assert.equal(stream[0].type, 'answer')
  assert.equal((stream[0] as { done: boolean }).done, true)
  assert.deepEqual(stream[1], { type: 'tool_call', tool_call_id: 'c1', tool_name: 'search', pending: true, tool_data: {} })
})

test('tool completion and failure update the same call', () => {
  const ok = toAgentEventStream([
    ev('tool.started', { invocation_id: 'c1', name: 'search' }),
    ev('tool.completed', { invocation_id: 'c1', summary: '3 条结果' }),
  ], 'running')
  assert.deepEqual(ok, [{ type: 'tool_call', tool_call_id: 'c1', tool_name: 'search', pending: false, success: true, tool_data: { summary: '3 条结果', error_code: undefined } }])

  const failed = toAgentEventStream([
    ev('tool.started', { invocation_id: 'c2', name: 'fetch' }),
    ev('tool.failed', { invocation_id: 'c2', error_code: 'timeout' }),
  ], 'failed')
  assert.equal((failed[0] as { success: boolean }).success, false)
  assert.equal((failed[0] as { tool_data: { error_code?: string } }).tool_data.error_code, 'timeout')
})

test('a new turn starts a new answer and the previous one is done', () => {
  const stream = toAgentEventStream([
    ev('message.delta', { text: 'a', turn: 0 }),
    ev('message.delta', { text: 'b', turn: 1 }),
  ], 'running')
  assert.equal(stream.length, 2)
  assert.equal((stream[0] as { done: boolean }).done, true)
  assert.equal((stream[1] as { done: boolean }).done, false)
})

test('a terminal run closes the open answer; cancellation appends stop', () => {
  const done = toAgentEventStream([ev('message.delta', { text: 'x', turn: 0 })], 'completed')
  assert.equal((done[0] as { done: boolean }).done, true)
  assert.equal(done.some(e => e.type === 'stop'), false)

  const cancelled = toAgentEventStream([ev('message.delta', { text: 'x', turn: 0 })], 'cancelled')
  assert.equal(cancelled[cancelled.length - 1].type, 'stop')
})

test('progress and input events are not part of the timeline', () => {
  const stream = toAgentEventStream([ev('tool.progress', { invocation_id: 'c1' }), ev('input.requested', {})], 'waiting_input')
  assert.deepEqual(stream, [])
})
