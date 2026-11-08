import assert from 'node:assert/strict'
import test from 'node:test'
import type { AgentToolEntry, TenantSkill } from '@/api/nexus-agents'
import { bundleFileName, rowBadges, runReasonKey, runState, sortLibrary } from './toolboxSkills'
import { groupTools, toolAction, toolState } from './toolboxTools'

const skill = (over: Partial<TenantSkill> = {}): TenantSkill => ({
  name: 'a', source: 'admin', scope: 'space', source_tenant_id: 't', version: 1, version_id: 'v', tools: [],
  execution: 'sandbox', model_invocable: true, description: '', disabled: false, ...over })
const tool = (over: Partial<AgentToolEntry> = {}): AgentToolEntry => ({
  name: 'x', description: '', group: 'base', risk_level: 'low', read_only: false, requires_approval: false,
  side_effects: false, enabled_in_tenant: true, ...over })

test('a healthy space skill has no badges; each condition adds a word', () => {
  assert.deepEqual(rowBadges(skill()), [])
  assert.deepEqual(rowBadges(skill({ scope: 'builtin', disabled: true, model_invocable: false, execution: 'local' })),
    ['builtin', 'disabled', 'hidden', 'host'])
  assert.deepEqual(rowBadges(skill({ version_id: null, version: null })), ['unavailable'])
  assert.deepEqual(rowBadges(skill({ verdict: 'caution', rescan_needed: true })), ['caution', 'rescan'])
  assert.deepEqual(rowBadges(skill({ verdict: 'dangerous' })), ['dangerous'])
})

test('script state: none without scripts, ok, or blocked with the reason', () => {
  assert.deepEqual(runState(skill()), { kind: 'none' })
  assert.deepEqual(runState(skill({ run: { ok: true, reason: '' } })), { kind: 'ok' })
  assert.deepEqual(runState(skill({ run: { ok: false, reason: 'sandbox_disabled' } })), { kind: 'blocked', reason: 'sandbox_disabled' })
  assert.equal(runReasonKey('sandbox_not_accepted'), 'nexusAgent.sandboxProfile.reasonNotAccepted')
  assert.equal(runReasonKey('local_not_allowed'), 'nexusAgent.sandboxProfile.reasonSkillLocal')
  assert.equal(runReasonKey('something_new'), 'nexusAgent.sandboxProfile.reasonOther')
})

test('the library lists the space\'s own skills before builtin ones, each by name', () => {
  const order = sortLibrary([skill({ name: 'z', scope: 'builtin' }), skill({ name: 'b' }), skill({ name: 'a', scope: 'builtin' }), skill({ name: 'a' })])
  assert.deepEqual(order.map((s) => `${s.scope}:${s.name}`), ['space:a', 'space:b', 'builtin:a', 'builtin:z'])
  assert.equal(bundleFileName('notes'), 'notes.zip')
  assert.equal(bundleFileName('notes', 3), 'notes-v3.zip')
})

test('tool state and the action an administrator has', () => {
  assert.equal(toolState(tool()), 'available')
  assert.equal(toolState(tool({ disabled: true, builtin: true })), 'disabled')
  assert.equal(toolState(tool({ enabled_in_tenant: false })), 'notEnabled')
  assert.equal(toolAction(tool({ builtin: true })), 'disable')
  assert.equal(toolAction(tool({ builtin: true, disabled: true })), 'restore')
  assert.equal(toolAction(tool({ enabled_in_tenant: false })), 'enable')
  assert.equal(toolAction(tool()), null)
})

test('tools are grouped in catalog order and empty or unknown groups are handled', () => {
  const sections = groupTools([tool({ name: 'b', group: 'memory' }), tool({ name: 'a', group: 'base' }), tool({ name: 'c', group: 'new' })], ['base', 'memory', 'skills'])
  assert.deepEqual(sections.map((s) => [s.key, s.tools.map((t) => t.name)]), [['base', ['a']], ['memory', ['b']], ['new', ['c']]])
  assert.deepEqual(groupTools([], ['base']), [])
})
