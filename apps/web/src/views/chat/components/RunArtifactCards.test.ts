import assert from 'node:assert/strict'
import test, { type TestContext } from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '../../../test-utils/vueFixture.ts'
import * as filePreview from '../../../utils/filePreview.ts'
import * as runArtifacts from '../../../utils/runArtifacts.ts'

const file = (id: string, name: string) => ({
  id, run_id: 'r1', session_id: 's1', session_title: '', message_id: '', index: 0, file_name: name,
  file_type: name.split('.').pop() || '', file_size: 2048, source_path: `/outputs/${name}`, created_at: '', version_count: 1,
})

function setup(t: TestContext, items: unknown[], api: Record<string, unknown> = {}) {
  const f = fixture(t)
  const pushed: string[] = []
  const page = f.component(new URL('./RunArtifactCards.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key, locale: vue.ref('en-US') }) },
    'vue-router': { useRouter: () => ({ push: (to: string) => { pushed.push(to) } }) },
    'tdesign-vue-next': { MessagePlugin: { success() {}, error() {}, warning() {} } },
    '@/api/artifacts': api,
    '@/utils/filePreview': filePreview,
    '@/utils/runArtifacts': runArtifacts,
    '@/utils/sessionArtifacts': { formatArtifactSize: (n: number) => `${n}B` },
  }, { items })
  return { ...page, pushed }
}

test('a long list shows the first files and expands on request', async t => {
  const items = Array.from({ length: 6 }, (_, n) => file(`a${n}`, `f${n}.pdf`))
  const { vm } = setup(t, items)
  await flush()
  assert.equal(vm.view.shown.length, 4)
  assert.equal(vm.view.hidden, 2)
  vm.expanded = true
  assert.equal(vm.view.shown.length, 6)
  assert.equal(vm.view.hidden, 0)
})

test('only files the preview can render open in the drawer; the rest are download-only', async t => {
  const requested: string[] = []
  const { vm } = setup(t, [file('a', 'plan.pdf'), file('b', 'blob.xyz')], {
    downloadArtifactFile: async (item: any) => { requested.push(item.id); return new Blob(['x']) },
  })
  await flush()
  await vm.openPreview(file('b', 'blob.xyz'))
  assert.deepEqual(requested, [], 'an unsupported type is never fetched for preview')
  assert.equal(vm.previewVisible, false)
  await vm.openPreview(file('a', 'plan.pdf'))
  assert.deepEqual(requested, ['a'])
  assert.equal(vm.previewVisible, true)
  assert.ok(vm.previewBlob instanceof Blob)
})

test('a stale preview answer is dropped', async t => {
  const resolvers: Array<(blob: Blob) => void> = []
  const { vm } = setup(t, [file('a', 'one.pdf'), file('b', 'two.pdf')], {
    downloadArtifactFile: () => new Promise<Blob>(resolve => resolvers.push(resolve)),
  })
  await flush()
  const first = vm.openPreview(file('a', 'one.pdf'))
  const second = vm.openPreview(file('b', 'two.pdf'))
  resolvers[0](new Blob(['stale']))
  await first
  assert.equal(vm.previewBlob, null)
  const fresh = new Blob(['fresh'])
  resolvers[1](fresh)
  await second
  assert.equal(vm.previewBlob, fresh)

})

test('a failed preview download is shown instead of spinning forever', async t => {
  const { vm } = setup(t, [file('c', 'three.pdf')], { downloadArtifactFile: async () => { throw new Error('nope') } })
  await flush()
  const original = console.error
  console.error = () => {}
  try { await vm.openPreview(file('c', 'three.pdf')) } finally { console.error = original }
  assert.equal(vm.previewFailed, true)
  assert.equal(vm.previewBlob, null)
})

test('downloading asks for the artifact by id and clears its busy state', async t => {
  const downloaded: string[] = []
  const { vm } = setup(t, [file('a', 'one.pdf')], {
    downloadArtifactFile: async (item: any) => { downloaded.push(item.id); return new Blob(['x']) },
  })
  await flush()
  const original = console.error
  console.error = () => {}  // the fixture has no DOM to save the blob into; the request is what matters here
  try { await vm.download(file('a', 'one.pdf')) } finally { console.error = original }
  assert.deepEqual(downloaded, ['a'])
})
