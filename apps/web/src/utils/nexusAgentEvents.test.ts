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

test('progress events and malformed prompts are not part of the timeline', () => {
  const stream = toAgentEventStream([ev('tool.progress', { invocation_id: 'c1' }), ev('input.requested', {})], 'waiting_input')
  assert.deepEqual(stream, [])
})

test('an input request becomes an ask_user card resolved by input.received', () => {
  const open = toAgentEventStream([ev('input.requested', { input_request_id: 'q1', question: 'Which?', candidates: ['A', 'B'] })], 'waiting_input')
  assert.deepEqual(open, [{ type: 'agent_prompt_required', kind: 'ask_user', pending_id: 'q1',
    request: { question: 'Which?', options: ['A', 'B'], allow_free_text: true }, resolved: false }])
  const answered = toAgentEventStream([ev('input.requested', { input_request_id: 'q1', question: 'Which?' }),
    ev('input.received', { input_request_id: 'q1' })], 'running')
  assert.equal((answered[0] as { answered?: boolean }).answered, true)
})

test('an approval becomes a tool_approval_required card with arguments from the approvals API', () => {
  const args = new Map([['a1', { path: '/tmp/x' }]])
  const stream = toAgentEventStream([ev('approval.requested', { approval_id: 'a1', tool_name: 'run_skill_script' })],
    'waiting_approval', { approvalArgs: args })
  assert.equal(stream[0].type, 'tool_approval_required')
  assert.equal((stream[0] as { mcp_tool_name: string }).mcp_tool_name, 'run_skill_script')
  assert.match((stream[0] as { args_json: string }).args_json, /\/tmp\/x/)
  const resolved = toAgentEventStream([ev('approval.requested', { approval_id: 'a1', tool_name: 't' }),
    ev('approval.resolved', { approval_id: 'a1', approved: false })], 'running')
  assert.equal((resolved[0] as { resolved: boolean; approved?: boolean }).approved, false)
})

test('cards still open when the run ends are shown as canceled', () => {
  const stream = toAgentEventStream([ev('approval.requested', { approval_id: 'a1', tool_name: 't' })], 'cancelled')
  assert.equal((stream[0] as { canceled?: boolean }).canceled, true)
})

test('a failed run ends with its failure text as the answer, like WeKnora run errors', () => {
  const failed = [ev('message.delta', { text: 'partial', turn: 0 }), ev('run.failed', { status: 'failed', error_code: 'model_timeout' })]
  const stream = toAgentEventStream(failed, 'failed', { failureMessage: code => `failed: ${code}` })
  const last = stream[stream.length - 1] as { type: string; content: string; done: boolean }
  assert.equal(last.type, 'answer')
  assert.equal(last.content, 'failed: model_timeout')
  assert.equal(last.done, true)
  assert.equal(toAgentEventStream(failed, 'failed').length, 1)
})
