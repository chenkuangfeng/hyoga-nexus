import assert from 'node:assert/strict'
import test, { type TestContext } from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
import * as library from '../../utils/artifactLibrary.ts'

const row = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, session_id: `s-${id}`, session_title: 'Work', message_id: '', index: 0, file_name: name, file_type: name.split('.').pop(),
  file_size: 10, source_path: `/outputs/${name}`, created_at: '2026-11-11T08:00:00Z', version_count: 1, ...extra,
})

function setup(t: TestContext, api: Record<string, unknown>, confirm: (options: any) => void = () => {}) {
  const f = fixture(t)
  const pushed: string[] = []
  const page = f.component(new URL('./ArtifactLibrary.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key, locale: vue.ref('en-US') }) },
    'vue-router': { useRoute: () => ({ params: {}, query: {} }), useRouter: () => ({ replace() {}, push: (to: string) => { pushed.push(to) } }) },
    'tdesign-vue-next': { MessagePlugin: { success() {}, error() {}, warning() {} } },
    '@nexus-web/core/api/artifacts': api,
    '@/utils/artifactLibrary': library,
    '@/utils/sessionArtifacts': { formatArtifactDateTime: (v: string) => v, formatArtifactSize: (v: number) => `${v}B` },
    '@/utils/filePreview': { resolveFilePreviewExt: (name: string, type: string) => type || name.split('.').pop() },
    '@/components/settings/useConfirmDelete': { useConfirmDelete: () => confirm },
  }, {})
  return { ...page, pushed }
}

test('the library loads newest versions with the server total and pages by the rows shown', async t => {
  const calls: any[] = []
  const { vm } = setup(t, {
    listArtifactLibrary: async (params: any) => {
      calls.push(params)
      return { data: [row('a', 'one.pdf'), row('b', 'two.md')], total: 3 }
    },
  })
  await flush()
  assert.deepEqual(vm.items.map((i: any) => i.id), ['a', 'b'])
  assert.equal(vm.total, 3)
  assert.equal(vm.hasMore, true)
  assert.equal(calls[0].page, 1)
})

test('opening a file fetches its bytes once and a stale answer is ignored', async t => {
  const resolvers: Array<(blob: Blob) => void> = []
  const requested: string[] = []
  const { vm } = setup(t, {
    listArtifactLibrary: async () => ({ data: [row('a', 'one.pdf'), row('b', 'two.md')], total: 2 }),
    downloadArtifactFile: (item: any) => { requested.push(item.id); return new Promise<Blob>(resolve => resolvers.push(resolve)) },
  })
  await flush()
  const first = vm.openPreview(vm.items[0])
  const second = vm.openPreview(vm.items[1])
  assert.equal(vm.previewVisible, true)
  assert.equal(vm.previewBlob, null)
  resolvers[0](new Blob(['stale']))
  await first
  assert.equal(vm.previewBlob, null, 'the answer for a file that is no longer shown is dropped')
  const wanted = new Blob(['fresh'])
  resolvers[1](wanted)
  await second
  assert.equal(vm.previewBlob, wanted)
  assert.deepEqual(requested, ['a', 'b'])
})

test('a failed preview download is reported instead of spinning forever', async t => {
  const { vm } = setup(t, {
    listArtifactLibrary: async () => ({ data: [row('a', 'one.pdf')], total: 1 }),
    downloadArtifactFile: async () => { throw new Error('boom') },
  })
  await flush()
  const originalError = console.error
  console.error = () => {}
  try {
    await vm.openPreview(vm.items[0])
  } finally {
    console.error = originalError
  }
  assert.equal(vm.previewFailed, true)
  assert.equal(vm.previewBlob, null)
})

test('delete asks first, then removes the file with every version by its id', async t => {
  const deleted: any[] = []
  let confirmOptions: any
  const { vm } = setup(t, {
    listArtifactLibrary: async () => ({ data: [row('a', 'one.pdf', { version_count: 3 }), row('b', 'two.md')], total: 2 }),
    deleteArtifactLibraryItem: async (item: any) => { deleted.push(item.id) },
  }, options => { confirmOptions = options })
  await flush()
  vm.handleDelete(vm.items[0])
  assert.deepEqual(deleted, [], 'nothing is deleted before the user confirms')
  assert.equal(confirmOptions.body, 'artifactLibrary.deleteConfirmVersions')
  await confirmOptions.onConfirm()
  assert.deepEqual(deleted, ['a'])
  assert.deepEqual(vm.items.map((i: any) => i.id), ['b'])
  assert.equal(vm.total, 1)
})

test('download goes through the artifact download and opening a session navigates to it', async t => {
  const downloaded: string[] = []
  const { vm, pushed } = setup(t, {
    listArtifactLibrary: async () => ({ data: [row('a', 'one.pdf')], total: 1 }),
    downloadArtifactFile: async (item: any) => { downloaded.push(item.id); return new Blob(['x']) },
  })
  await flush()
  // The fixture's `document` has no DOM, so saving the blob fails after the request; the page must still clear its state.
  const originalError = console.error
  console.error = () => {}
  try {
    await vm.handleDownload(vm.items[0])
  } finally {
    console.error = originalError
  }
  assert.deepEqual(downloaded, ['a'], 'the file is requested by its artifact id')
  assert.equal(vm.isDownloading(vm.items[0]), false)
  vm.openSession(vm.items[0])
  assert.deepEqual(pushed, ['/platform/chat/s-a'])
})
