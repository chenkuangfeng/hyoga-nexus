import assert from 'node:assert/strict'
import { test } from 'node:test'

import { COLLAPSED_LIMIT, groupArtifactsByRun, visibleArtifacts } from './runArtifacts.ts'

const item = (id: string, run: string | undefined, path: string) => ({
  id, run_id: run, source_path: path, session_id: 's', session_title: '', message_id: '', index: 0, file_name: path,
  file_type: '', file_size: 1, created_at: '', version_count: 1,
})

test('artifacts are grouped by the Run that left them and ordered by path', () => {
  const groups = groupArtifactsByRun([
    item('3', 'r1', '/outputs/b.txt'), item('1', 'r2', '/outputs/x.txt'), item('2', 'r1', '/outputs/a.txt'),
    item('4', undefined, '/outputs/orphan.txt'), item('5', '', '/outputs/orphan2.txt'),
  ])
  assert.deepEqual([...groups.keys()], ['r1', 'r2'])
  assert.deepEqual(groups.get('r1')!.map(i => i.id), ['2', '3'])
  assert.equal(groups.get('r3'), undefined)
})

test('a long list collapses behind an expander and shows everything once expanded', () => {
  const files = Array.from({ length: COLLAPSED_LIMIT + 3 }, (_, n) => n)
  assert.deepEqual(visibleArtifacts(files, false).hidden, 3)
  assert.equal(visibleArtifacts(files, false).shown.length, COLLAPSED_LIMIT)
  assert.deepEqual(visibleArtifacts(files, true), { shown: files, hidden: 0 })
  assert.deepEqual(visibleArtifacts([1, 2], false), { shown: [1, 2], hidden: 0 })
  assert.deepEqual(visibleArtifacts(files, false, 100), { shown: files, hidden: 0 })
})
