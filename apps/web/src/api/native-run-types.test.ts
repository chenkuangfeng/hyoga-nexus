import assert from 'node:assert/strict'
import { test } from 'node:test'

import { isRunEvent, isRunView } from './native-run-types'

const validRun = {
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
}

test('isRunView accepts the server shape and rejects unknown statuses and missing flags', () => {
  assert.equal(isRunView(validRun), true)
  assert.equal(isRunView({ ...validRun, status: 'paused' }), false)
  assert.equal(isRunView({ ...validRun, attention_required: undefined }), false)
  assert.equal(isRunView({ ...validRun, queue_position: '2' }), false)
  assert.equal(isRunView(null), false)
  assert.equal(isRunView([]), false)
})

test('isRunEvent requires a positive integer sequence and an object payload', () => {
  const event = {
    event_id: 'e1', run_id: 'run-1', sequence: 1, event_type: 'message.delta',
    schema_version: 1, payload: { text: 'hi' }, occurred_at: '2026-11-04T00:00:00Z',
  }
  assert.equal(isRunEvent(event), true)
  assert.equal(isRunEvent({ ...event, sequence: 0 }), false)
  assert.equal(isRunEvent({ ...event, sequence: 1.5 }), false)
  assert.equal(isRunEvent({ ...event, payload: 'text' }), false)
  assert.equal(isRunEvent({ ...event, event_type: undefined }), false)
})
