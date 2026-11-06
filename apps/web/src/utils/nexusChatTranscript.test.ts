import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { ConversationMessage, RunEvent } from '../api/native-run-types.ts'
import { buildChatRows, runsNeedingEvents, statusFromEvents, transcriptMarkdown } from './nexusChatTranscript.ts'

let seq = 0
function msg(role: string, content: string, runId: string | null): ConversationMessage {
  seq += 1
  return { id: `m${seq}`, run_id: runId, sequence: seq, role, content, created_at: `2026-11-05T10:00:0${seq % 10}Z` }
}
function ev(runId: string, type: string, payload: Record<string, unknown> = {}, sequence = 1): RunEvent {
  return { event_id: `${runId}-${sequence}`, run_id: runId, sequence, event_type: type, schema_version: 1, payload, occurred_at: '' } as RunEvent
}

test('user messages and one assistant row per run, tool rows folded into the run', () => {
  const messages = [msg('user', 'hi', 'r1'), msg('assistant', '', 'r1'), msg('tool', 'out', 'r1'), msg('assistant', 'Answer', 'r1'),
    msg('user', 'again', 'r2'), msg('assistant', 'Second', 'r2')]
  const rows = buildChatRows(messages, new Map())
  assert.deepEqual(rows.map(r => r.role), ['user', 'assistant', 'user', 'assistant'])
  const first = rows[1] as { content: string; isAgentMode: boolean; is_completed: boolean }
  assert.equal(first.content, 'Answer')
  assert.equal(first.isAgentMode, false)
  assert.equal(first.is_completed, true)
})

test('a run with events renders its timeline', () => {
  const messages = [msg('user', 'hi', 'r1'), msg('assistant', 'Hello', 'r1')]
  const events = new Map([['r1', [ev('r1', 'message.delta', { text: 'Hello', turn: 0 }, 1), ev('r1', 'run.completed', {}, 2)]]])
  const row = buildChatRows(messages, events)[1] as { isAgentMode: boolean; agentEventStream: Array<{ type: string; done?: boolean }> }
  assert.equal(row.isAgentMode, true)
  assert.equal(row.agentEventStream[0].type, 'answer')
  assert.equal(row.agentEventStream[0].done, true)
})

test('pending inputs and the live run are appended until persisted', () => {
  const live = { id: 'r9', status: 'running', events: [ev('r9', 'message.delta', { text: 'typing', turn: 0 })] }
  const rows = buildChatRows([msg('user', 'hi', 'r1'), msg('assistant', 'a', 'r1')], new Map(), ['next'], live)
  assert.deepEqual(rows.map(r => r.role), ['user', 'assistant', 'user', 'assistant'])
  assert.equal((rows[3] as { is_completed: boolean }).is_completed, false)
  const persisted = buildChatRows([msg('user', 'x', 'r9'), msg('assistant', 'done', 'r9')], new Map(), [],
    { id: 'r9', status: 'completed', events: live.events })
  assert.equal(persisted.filter(r => r.role === 'assistant').length, 1)
})

test('terminal status comes from the run event; events are requested once per finished run', () => {
  assert.equal(statusFromEvents([ev('r', 'run.started'), ev('r', 'run.cancelled', {}, 2)]), 'cancelled')
  assert.equal(statusFromEvents([]), 'completed')
  const messages = [msg('user', 'a', 'r1'), msg('assistant', 'b', 'r1'), msg('user', 'c', 'r2')]
  assert.deepEqual(runsNeedingEvents(messages, new Set(['r1']), 'r3'), ['r2'])
})

test('copy as markdown lists turns under the title', () => {
  const rows = buildChatRows([msg('user', 'Q', 'r1'), msg('assistant', 'A', 'r1')], new Map())
  assert.equal(transcriptMarkdown('T', rows, { user: 'User', assistant: 'Assistant' }), '# T\n\n## User\n\nQ\n\n## Assistant\n\nA\n')
})

test('assistant rows carry the memories their Run used', () => {
  const messages = [msg('user', '你好', 'r1'), msg('assistant', '好的', 'r1')]
  const events = new Map([['r1', [
    ev('r1', 'memory.used', { source: 'resident', entries: [{ id: 'p1', title: '风格', kind: 'profile', version: 1 }] }, 1),
    ev('r1', 'run.completed', {}, 2),
  ]]])
  const [, row] = buildChatRows(messages, events)
  assert.equal(row.role, 'assistant')
  assert.deepEqual(row.role === 'assistant' ? row.used_memories : null, [{ id: 'p1', kind: 'profile', content: '风格' }])
})

test('knowledge citations of a Run are merged by handle onto its answer row', () => {
  const rows = buildChatRows([
    { id: 'u', run_id: 'r1', sequence: 1, role: 'user', content: 'q', created_at: '' },
    { id: 'a1', run_id: 'r1', sequence: 2, role: 'assistant', content: 'x [ID:2] [ID:1]', created_at: '',
      citations: [{ handle: 2, chunk_id: 'c2', filename: 'b.md' }, { handle: 1, chunk_id: 'c1', filename: 'a.md' }] },
    { id: 'a2', run_id: 'r1', sequence: 3, role: 'assistant', content: 'y [ID:1]', created_at: '',
      citations: [{ handle: 1, chunk_id: 'c1', filename: 'a.md' }] },
  ] as never, new Map(), [], null)
  const answer = rows.find(row => row.role === 'assistant')
  assert.ok(answer && answer.role === 'assistant')
  assert.deepEqual(answer.citations.map(item => item.handle), [1, 2])
})
