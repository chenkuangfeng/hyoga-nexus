import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import * as marked from 'marked'
import * as literalTilde from '../../utils/markedLiteralTilde.ts'
import * as sorting from '../../utils/resourceSorting.ts'
import { change, fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

test('refreshes data source controls after assistant changes and stops on unmount', async t => {
  const f = fixture(t)
  const listDataSources = t.mock.fn(async (_id: string) => ({ data: [] }))
  const { close } = f.component(new URL('../../../../core/src/components/knowledge-editor/settings/DataSourceSettings.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { MessagePlugin: { error: assert.fail } },
    '@nexus-web/core/stores/auth': { useAuthStore: () => ({ hasRole: () => true }) },
    '../../../utils/cronHumanize': {},
    '../../../composables/useConnectorLabel': { useConnectorLabel: () => ({ connectorLabel: (type: string) => type }) },
    '../scopedApi': { useScopedApi: (api: unknown) => api },
    '@nexus-web/core/api/datasource/index': { listDataSources },
  }, { kbId: 'kb' })
  await flush()
  listDataSources.mock.resetCalls()
  f.emit(change('agent.update'))
  t.mock.timers.tick(300)
  assert.equal(listDataSources.mock.callCount(), 0)
  f.emit(change('data_source.pause'))
  f.emit(change('data_source.sync'))
  f.emit(change('data_source.update_sync'))
  t.mock.timers.tick(300)
  await flush()
  assert.equal(listDataSources.mock.callCount(), 1)
  assert.equal(listDataSources.mock.calls[0].arguments[0], 'kb')
  close()
  f.emit(change('data_source.resume'))
  t.mock.timers.tick(300)
  assert.equal(listDataSources.mock.callCount(), 1)
})

test('refreshes the FAQ entries and tags once per burst for its own KB only', async t => {
  const f = fixture(t)
  const listFAQEntries = t.mock.fn(async (_id: string, _params: unknown) => ({ data: { data: [], total: 1 } }))
  const listKnowledgeTags = t.mock.fn(async (_id: string, _params: unknown) => ({ data: { data: [], total: 0 } }))
  f.component(new URL('./components/FAQEntryManager.vue', import.meta.url), {
    'vue-router': { useRouter: () => ({}) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { MessagePlugin: { error: assert.fail } },
    '@/components/settings/useConfirmDelete': { useConfirmDelete: () => ({}) },
    '@nexus-web/core/stores/auth': { useAuthStore: () => ({ hasRole: () => true }) },
    '@/stores/ui': { useUIStore: () => ({ clearSelectedTagIds() {} }) },
    '@nexus-web/core/stores/organization': { useOrganizationStore: () => ({ sharedKnowledgeBases: [], async fetchSharedKnowledgeBases() {} }) },
    '@nexus-web/core/stores/chatResources': { useChatResourcesStore: () => ({ rawKnowledgeBases: [], async ensureKnowledgeBases() {} }) },
    '@nexus-web/core/api/knowledge-base/index': {
      listFAQEntries, listKnowledgeTags,
      getKnowledgeBaseById: async () => ({ data: { id: 'kb', type: 'faq' } }),
    },
    xlsx: {}, papaparse: {},
  }, { kbId: 'kb' })
  await flush()
  listFAQEntries.mock.resetCalls()
  listKnowledgeTags.mock.resetCalls()
  f.emit(change('faq.update_entry', { knowledge_base_id: ['other'] }))
  f.emit(change('agent.create', { knowledge_base_id: ['kb'] }))
  t.mock.timers.tick(300)
  assert.equal(listFAQEntries.mock.callCount(), 0)
  assert.equal(listKnowledgeTags.mock.callCount(), 0)
  f.emit(change('faq.batch_update', { knowledge_base_id: ['kb'] }))
  f.emit(change('faq.delete_entries', { knowledge_base_id: ['kb'] }))
  t.mock.timers.tick(300)
  await flush()
  assert.equal(listFAQEntries.mock.callCount(), 1)
  assert.equal(listKnowledgeTags.mock.callCount(), 1)
  assert.equal(listFAQEntries.mock.calls[0].arguments[0], 'kb')
  assert.equal(listKnowledgeTags.mock.calls[0].arguments[0], 'kb')
  assert.equal((listKnowledgeTags.mock.calls[0].arguments[1] as any).page, 1)
})

test('refreshes Wiki pages, selected content and statistics for its own KB only', async t => {
  const f = fixture(t)
  const page = { id: 'page', slug: 'page', title: 'Updated title', content: '', version: 2 }
  const getWikiPage = t.mock.fn(async (_id: string, _slug: string) => ({ data: page }))
  const getWikiIndex = t.mock.fn(async () => ({ groups: [] }))
  const getWikiStats = t.mock.fn(async () => ({}))
  const { vm } = f.component(new URL('./wiki/WikiBrowser.vue', import.meta.url), {
    marked,
    'vue-router': { useRouter: () => ({}), useRoute: () => ({ query: {} }) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { MessagePlugin: { error: assert.fail } },

    '@/stores/settings': { useSettingsStore: () => ({}) },
    '@nexus-web/core/api/wiki/index': {
      getWikiPage, getWikiIndex, getWikiStats,
      listWikiIssues: async () => [], listWikiPages: async () => ({ pages: [], total: 0 }),
      listWikiFolders: async () => ({ folders: [] }),
    },
    '@/utils/security': { sanitizeMarkdownHTML: (html: string) => html, hydrateProtectedFileImages: async () => {} },
    '@/utils/markedLiteralTilde': literalTilde,
    'vue-virtual-scroller': {}, '@nexus-web/core/api/knowledge-base/index': {}, '@nexus-web/core/api/chat/index': {},
  }, { knowledgeBaseId: 'kb' })
  await flush()
  vm.selectedPage = { ...page, title: 'Old title' }
  const reloads = [getWikiPage, getWikiIndex, getWikiStats]
  reloads.forEach(reload => reload.mock.resetCalls())
  f.emit(change('wiki.revert', { knowledge_base_id: ['other'] }))
  f.emit(change('agent.create', { knowledge_base_id: ['kb'] }))
  t.mock.timers.tick(300)
  reloads.forEach(reload => assert.equal(reload.mock.callCount(), 0))
  f.emit(change('wiki.revert', { knowledge_base_id: ['kb'] }))
  f.emit(change('wiki.revert', { knowledge_base_id: ['kb'] }))
  t.mock.timers.tick(300)
  await flush()
  reloads.forEach(reload => assert.equal(reload.mock.callCount(), 1))
  assert.deepEqual(Array.from(getWikiPage.mock.calls[0].arguments), ['kb', 'page'])
  assert.equal(vm.selectedPage.title, 'Updated title')
})

test('refreshes the employee KB directory for knowledge_base changes only', async t => {
  const f = fixture(t)
  const listKnowledgeBases = t.mock.fn(async () => ({ data: [{ id: 'kb', name: 'Updated KB' }] }))
  const { vm } = f.component(new URL('./KnowledgeBaseList.vue', import.meta.url), {
    'vue-router': { useRouter: () => ({}) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@nexus-web/core/stores/auth': { useAuthStore: () => ({ effectiveTenantId: 'a', user: { id: 'u' }, currentTenantRole: 'owner' }) },
    '@nexus-web/core/api/knowledge-base/index': { listKnowledgeBases },
  })
  await flush(); listKnowledgeBases.mock.resetCalls()
  f.emit(change('unknown.update')); t.mock.timers.tick(300)
  assert.equal(listKnowledgeBases.mock.callCount(), 0)
  f.emit(change('knowledge_base.generate_profile')); t.mock.timers.tick(300); await flush()
  assert.equal(listKnowledgeBases.mock.callCount(), 1)
  assert.equal(vm.rows[0].name, 'Updated KB')
})
