import assert from 'node:assert/strict'
import test from 'node:test'
import type { MySkill } from '@/api/nexus-agents'
import { isOffered, skillBadges } from './mySkills'

const base: MySkill = { name: 'a', version: 1, description: '', verdict: 'safe', model_invocable: true, archived: false,
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
