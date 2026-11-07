import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { RunEvent } from '../api/native-run-types.ts'
import { toAgentEventStream, usedMemoriesFromEvents } from './nexusAgentEvents.ts'

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

test('a proposed memory draft becomes a reviewable card and closes the open answer', () => {
  const stream = toAgentEventStream([
    ev('message.delta', { text: '我记一下', turn: 0 }),
    ev('memory.draft_proposed', {
      draft_id: 'd1', kind: 'memory', diff: '构建改用 bazel', topic: '构建',
      base_entry: { id: 'm1', title: '构建', version: 2 },
      annotations: { conflict: [{ entry_id: 'm9', title: '旧构建方式' }] },
    }),
  ], 'running')
  assert.equal((stream[0] as { done: boolean }).done, true)
  assert.deepEqual(stream[1], {
    type: 'memory_draft', draft_id: 'd1', kind: 'memory', diff: '构建改用 bazel', topic: '构建',
    base_entry: { id: 'm1', title: '构建', version: 2 }, conflicts: ['旧构建方式'], similar: [],
  })
})

test('a new-entry draft has no base entry and malformed hints are ignored', () => {
  const [card] = toAgentEventStream([ev('memory.draft_proposed', { draft_id: 'd2', diff: 'x', annotations: { conflict: 'no' } })], 'running')
  const [similar] = toAgentEventStream([ev('memory.draft_proposed', { draft_id: 'd3', diff: 'y', annotations: { similar: [{ entry_id: 'm2', title: '构建', score: 0.7 }] } })], 'running')
  assert.deepEqual((similar as { similar: string[] }).similar, ['构建'])
  assert.deepEqual(card, { type: 'memory_draft', draft_id: 'd2', kind: 'memory', diff: 'x', topic: '', base_entry: null, conflicts: [], similar: [] })
})

test('memory.used events are collected per entry and stay out of the timeline', () => {
  const events = [
    ev('memory.used', { source: 'resident', entries: [{ id: 'p1', title: '风格', kind: 'profile', version: 1 }] }),
    ev('memory.used', { source: 'read', entries: [{ id: 'm1', title: '构建', kind: 'memory', version: 2 }] }),
    ev('memory.used', { source: 'search', entries: [{ id: 'm1', title: '构建', kind: 'memory', version: 2 }, null] }),
  ]
  assert.deepEqual(toAgentEventStream(events, 'running'), [])
  assert.deepEqual(usedMemoriesFromEvents(events), [
    { id: 'p1', kind: 'profile', content: '风格' },
    { id: 'm1', kind: 'memory', content: '构建' },
  ])
})

test('approvals that may be remembered offer the session option and guard rules become the description', () => {
  const stream = toAgentEventStream([
    ev('approval.requested', { approval_id: 'a1', tool_name: 'write', reason: 'policy', rememberable: true }),
    ev('approval.requested', { approval_id: 'a2', tool_name: 'bash', reason: 'guard', rememberable: false,
      guard_rules: [{ id: 'TOOL_CMD_DANGEROUS_RM', description: '可能删除文件' }] }),
  ], 'waiting_approval')
  const [policy, guarded] = stream as Array<Record<string, unknown>>
  assert.equal(policy.grant_scope, 'write')
  assert.equal(guarded.grant_scope, undefined)
  assert.equal(guarded.description, '- 可能删除文件')
})

test('message.completed alone rebuilds a finished answer (history without stored deltas)', () => {
  const stream = toAgentEventStream([
    ev('tool.started', { invocation_id: 'c1', name: 'search' }),
    ev('tool.completed', { invocation_id: 'c1' }),
    ev('message.completed', { turn: 1, text: '结果如下' }),
  ], 'completed')
  assert.equal(stream.length, 2)
  assert.deepEqual(stream[1], { ...stream[1], type: 'answer', content: '结果如下', done: true })
})

test('message.completed replaces streamed text of the same turn and closes the answer', () => {
  const stream = toAgentEventStream([
    ev('message.delta', { text: '结果', turn: 1 }),
    ev('message.completed', { turn: 1, text: '结果如下' }),
    ev('message.delta', { text: '补充', turn: 2 }),
  ], 'running')
  assert.equal(stream.length, 2)
  assert.deepEqual(stream[0], { ...stream[0], content: '结果如下', done: true })
  assert.deepEqual(stream[1], { ...stream[1], content: '补充', done: false })
})
