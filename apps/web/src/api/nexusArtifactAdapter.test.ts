import assert from 'node:assert/strict'
import { test } from 'node:test'

import { extensionOf, toLibraryItem, toLibraryPage, toListQuery } from './nexusArtifactAdapter.ts'

test('an artifact becomes a library row addressed by its id', () => {
  const row = toLibraryItem({
    id: 'a1', session_id: 's1', run_id: 'r1', session_title: '周报', name: 'report.pdf', path: '/outputs/report.pdf', size: 2048,
    mime: 'application/pdf', created_at: '2026-11-11T08:00:00Z', version_count: 3,
  })
  assert.equal(row.id, 'a1')
  assert.equal(row.run_id, 'r1')
  assert.equal(row.file_name, 'report.pdf')
  assert.equal(row.file_size, 2048)
  assert.equal(row.file_type, 'pdf', 'the file type is the extension the preview picks a renderer by')
  assert.equal(row.session_title, '周报')
  assert.equal(row.version_count, 3)
  assert.equal(row.source_path, '/outputs/report.pdf')
  assert.equal(toLibraryItem({ id: 'a2' }).version_count, 1)
  assert.equal(toLibraryItem({ id: 'a2', version_count: 0 }).version_count, 1)
})

test('the list query carries the filters and turns pages into offsets', () => {
  const query = new URLSearchParams(toListQuery({ keyword: '  plan ', fileTypes: ['.pdf', '.md'], page: 3, pageSize: 30 }))
  assert.equal(query.get('q'), 'plan')
  assert.equal(query.get('extensions'), '.pdf,.md')
  assert.equal(query.get('limit'), '30')
  assert.equal(query.get('offset'), '60')
  assert.equal(query.get('latest'), 'true')
  const bare = new URLSearchParams(toListQuery({}))
  assert.equal(bare.get('q'), null)
  assert.equal(bare.get('extensions'), null)
  assert.equal(bare.get('offset'), '0')
  assert.equal(new URLSearchParams(toListQuery({ pageSize: 9999 })).get('limit'), '200')
})

test('the page keeps the server total and tolerates a malformed answer', () => {
  const page = toLibraryPage({ items: [{ id: 'a' }, { id: 'b' }], total: 7 }, 2, 2)
  assert.deepEqual([page.data.length, page.total, page.page, page.page_size], [2, 7, 2, 2])
  assert.equal(toLibraryPage({ items: [{ id: 'a' }] }, 1, 30).total, 1)
  assert.deepEqual(toLibraryPage(null as any, 1, 30).data, [])
})

test('the extension is lower-cased and absent for names without one', () => {
  assert.equal(extensionOf('Report.PDF'), 'pdf')
  assert.equal(extensionOf('archive.tar.gz'), 'gz')
  assert.equal(extensionOf('README'), '')
  assert.equal(extensionOf('trailing.'), '')
})
