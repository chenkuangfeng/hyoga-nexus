import assert from 'node:assert/strict'
import { test } from 'node:test'

import { isPlannedFeatureError } from './knowledge-base/nexusAdapter.ts'
import {
  ruleFromTrigger, toNexusCreateBody, toNexusUpdateBody, toWeKnoraAutomation, toWeKnoraRun, triggerFromRule,
} from './nexusAutomationAdapter.ts'

const cron = (expr: string, timezone = 'Asia/Shanghai') => ({ type: 'cron' as const, expr, timezone })

test('triggers map to the three Nexus rules and back', () => {
  assert.deepEqual(ruleFromTrigger(cron('@every 30m')), { kind: 'interval', every_minutes: 30 })
  assert.deepEqual(ruleFromTrigger(cron('@every 2h')), { kind: 'interval', every_minutes: 120 })
  assert.deepEqual(ruleFromTrigger(cron('30 9 * * *')), { kind: 'daily', at: '09:30' })
  assert.deepEqual(ruleFromTrigger(cron('5 18 * * 3')), { kind: 'weekly', weekday: 2, at: '18:05' })
  for (const rule of [{ kind: 'interval', every_minutes: 45 }, { kind: 'daily', at: '09:30' }, { kind: 'weekly', weekday: 0, at: '07:00' }]) {
    assert.deepEqual(ruleFromTrigger(triggerFromRule(rule, 'UTC')), rule)
  }
})

test('weekdays use cron numbering in triggers and Monday-first numbering in rules', () => {
  assert.equal(triggerFromRule({ kind: 'weekly', weekday: 0, at: '09:00' }, 'UTC').expr, '0 9 * * 1') // Monday
  assert.equal(triggerFromRule({ kind: 'weekly', weekday: 6, at: '09:00' }, 'UTC').expr, '0 9 * * 0') // Sunday
  assert.deepEqual(ruleFromTrigger(cron('0 9 * * 0')), { kind: 'weekly', weekday: 6, at: '09:00' })
})

test('triggers without an exact Nexus equivalent are planned features', () => {
  for (const expr of ['0 * * * *', '0 9 * * 1-5', '0 9 * * 1,3', '0 9 1 * *', '*/5 * * * *', '0 0 9 * * *', '']) {
    assert.throws(() => ruleFromTrigger(cron(expr)), (error) => isPlannedFeatureError(error), expr)
  }
  assert.throws(() => ruleFromTrigger({ type: 'once', at: '2026-11-12T01:00:00Z', timezone: 'UTC' }), (e) => isPlannedFeatureError(e))
  assert.throws(() => ruleFromTrigger(undefined), (e) => isPlannedFeatureError(e))
})

test('a Nexus task reads as a WeKnora automation with its Nexus-only fields', () => {
  const view = toWeKnoraAutomation({
    id: 'j1', name: '晨报', prompt: '总结新闻', rule: { kind: 'daily', at: '09:00' }, timezone: 'Asia/Shanghai',
    state: 'suspended', last_error: 'Forbidden', next_run_at: 'n', last_run_at: 'l', session_id: 's1', agent_id: 'a1',
    agent_name: '助手', agent_version: 2, run_count: 4, owner_user_id: 'u1', owner_name: '小王', created_at: 'c',
  })
  assert.equal(view.instruction, '总结新闻')
  assert.equal(view.enabled, false)
  assert.equal(view.paused_reason, 'Forbidden')
  assert.deepEqual(view.trigger, { type: 'cron', expr: '0 9 * * *', timezone: 'Asia/Shanghai' })
  assert.equal(view.session_mode, 'persistent')
  assert.equal(view.persistent_session_id, 's1')
  assert.equal(view.agent_name, '助手')
  assert.equal(view.owner_name, '小王')
  assert.equal(toWeKnoraAutomation({ id: 'j2', state: 'active' }).enabled, true)
  assert.equal(toWeKnoraAutomation({ id: 'j2', state: 'paused' }).paused_reason, '')
})

test('create and update bodies carry only what Nexus understands', () => {
  const create = toNexusCreateBody({
    name: ' 晨报 ', instruction: '总结', agent_id: 'a1', model_id: 'ignored', overlap_policy: 'queue',
    trigger: cron('0 9 * * *', 'Asia/Shanghai'),
  })
  assert.deepEqual(create, { name: '晨报', prompt: '总结', agent_id: 'a1', schedule: { kind: 'daily', at: '09:00' }, timezone: 'Asia/Shanghai' })
  assert.deepEqual(toNexusUpdateBody({ name: 'x' }), { name: 'x' })
  assert.deepEqual(toNexusUpdateBody({ trigger: cron('@every 30m', 'UTC'), notify_on_success: true }),
    { schedule: { kind: 'interval', every_minutes: 30 }, timezone: 'UTC' })
  assert.throws(() => toNexusCreateBody({ name: 'x', instruction: 'y', agent_id: 'a', trigger: cron('0 * * * *') }), (e) => isPlannedFeatureError(e))
})

test('run statuses map to automation run statuses', () => {
  const base = { id: 'r1', session_id: 's1', created_at: 'c', started_at: 's', ended_at: 'e', error_code: 'boom', cancel_requested: true }
  assert.equal(toWeKnoraRun({ ...base, status: 'completed' }, 'j1').status, 'succeeded')
  assert.equal(toWeKnoraRun({ ...base, status: 'waiting_approval' }, 'j1').status, 'awaiting_approval')
  assert.equal(toWeKnoraRun({ ...base, status: 'interrupted' }, 'j1').status, 'failed')
  const run = toWeKnoraRun({ ...base, status: 'running' }, 'j1')
  assert.deepEqual([run.automation_id, run.error, run.finished_at, run.cancel_requested, run.trigger_kind], ['j1', 'boom', 'e', true, 'schedule'])
})
