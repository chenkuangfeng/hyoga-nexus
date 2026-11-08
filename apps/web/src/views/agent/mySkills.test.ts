import assert from 'node:assert/strict'
import test from 'node:test'
import type { MySkill } from '@/api/nexus-agents'
import { isOffered, skillBadges } from './mySkills'

const base: MySkill = { use_count: 0, last_used_at: null, name: 'a', version: 1, description: '', verdict: 'safe', model_invocable: true, archived: false,
  superseded: false, latest_version: 1, latest_state: 'ready', latest_error: null, created_at: '' }

test('a healthy skill has no badges and is offered', () => {
  assert.deepEqual(skillBadges(base), [])
  assert.equal(isOffered(base), true)
})

test('archived and superseded skills are not offered and say why', () => {
  assert.deepEqual(skillBadges({ ...base, archived: true, superseded: true }), ['archived', 'superseded'])
  assert.equal(isOffered({ ...base, archived: true }), false)
  assert.equal(isOffered({ ...base, superseded: true }), false)
})

test('build state, hidden flag and caution verdict are reported', () => {
  assert.deepEqual(skillBadges({ ...base, latest_state: 'installing' }), ['installing'])
  assert.deepEqual(skillBadges({ ...base, latest_state: 'failed', model_invocable: false, verdict: 'caution' }),
    ['buildFailed', 'hiddenFromModel', 'caution'])
  assert.equal(isOffered({ ...base, version: null }), false)
})

import { shareAction, submissionErrorKey } from './mySkills'

test('administrators publish at once, submitters file a submission, others cannot share', () => {
  assert.equal(shareAction(['tools:manage', 'skills:submit']), 'share')
  assert.equal(shareAction(['skills:submit']), 'submit')
  assert.equal(shareAction(['agents:read']), null)
})

test('sharing failures map to a message group, unknown ones fall back', () => {
  assert.equal(submissionErrorKey('skill_base_changed'), 'nexusAgent.share.error.stale')
  assert.equal(submissionErrorKey('skill_submission_rate_limit'), 'nexusAgent.share.error.limit')
  assert.equal(submissionErrorKey('skill_name_taken_by_library'), 'nexusAgent.share.error.nameTaken')
  assert.equal(submissionErrorKey('whatever'), 'nexusAgent.share.error.other')
})

import { usageText } from './mySkills'

test('usage text: nothing for builtin skills, "never" before the first use, count and time after', () => {
  assert.equal(usageText(null, null), null)
  assert.equal(usageText(undefined, undefined), null)
  assert.deepEqual(usageText(0, null), { kind: 'never' })
  assert.deepEqual(usageText(3, '2026-11-08T10:30:12+00:00'), { kind: 'used', count: 3, when: '2026-11-08 10:30' })
})
