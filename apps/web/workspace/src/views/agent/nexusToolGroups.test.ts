import assert from 'node:assert/strict'
import { test } from 'node:test'

import { groupEnabled, groupReasonKey, groupStatus, switchesOf, withGroupSwitch } from './nexusToolGroups.ts'

const info = (patch = {}) => ({
  id: 'sandbox', label: '沙箱', default_enabled: false, locked: false, tool_count: 6, planned: '',
  available: true, reason: '', ...patch,
})

test('stored switches keep only booleans', () => {
  assert.deepEqual(switchesOf({ sandbox: true, web: 'yes', mcp: false }), { sandbox: true, mcp: false })
  assert.deepEqual(switchesOf(null), {})
  assert.deepEqual(switchesOf(['a']), {})
})

test('a group is on by the choice, else by its default; the base group is always on', () => {
  assert.equal(groupEnabled(info(), {}), false)
  assert.equal(groupEnabled(info(), { sandbox: true }), true)
  assert.equal(groupEnabled(info({ default_enabled: true, id: 'memory' }), { memory: false }), false)
  assert.equal(groupEnabled(info({ locked: true, id: 'base', default_enabled: true }), { base: false }), true)
})

test('setting a group to its default removes the explicit choice', () => {
  const on = withGroupSwitch({}, info(), true)
  assert.deepEqual(on, { sandbox: true })
  assert.deepEqual(withGroupSwitch(on, info(), false), {})
  assert.deepEqual(withGroupSwitch({ web: true }, info(), true), { web: true, sandbox: true })
  const memory = info({ id: 'memory', default_enabled: true })
  assert.deepEqual(withGroupSwitch({}, memory, false), { memory: false })
})

test('status tells locked, planned, unavailable, off and on apart', () => {
  assert.equal(groupStatus(info({ locked: true }), {}), 'locked')
  assert.equal(groupStatus(info({ planned: '工具扩展 G', tool_count: 0 }), {}), 'planned')
  assert.equal(groupStatus(info({ available: false, reason: 'sandbox_disabled' }), { sandbox: true }), 'unavailable')
  assert.equal(groupStatus(info(), {}), 'off')
  assert.equal(groupStatus(info(), { sandbox: true }), 'on')
  // A group that has tools is not "planned" even if the field still names a phase.
  assert.equal(groupStatus(info({ planned: 'x', tool_count: 2 }), { sandbox: true }), 'on')
})

test('reason codes map to messages and unknown codes fall back', () => {
  assert.equal(groupReasonKey('web_disabled'), 'reasonWebDisabled')
  assert.equal(groupReasonKey('sandbox_required'), 'reasonSandboxRequired')
  assert.equal(groupReasonKey('something_new'), 'reasonOther')
})
