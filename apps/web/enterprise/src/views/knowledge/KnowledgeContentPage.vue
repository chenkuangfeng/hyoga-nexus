<script setup lang="ts">
/** 企业知识库内容维护页：按库类型管理文档、FAQ 条目或 Wiki 页面。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import KbFolderTree from '@nexus-web/core/components/knowledge/documents/KbFolderTree.vue'
import KbDocumentLayout from '@nexus-web/core/components/knowledge/documents/KbDocumentLayout.vue'
import KbUploadSourceDropdown from '@nexus-web/core/components/knowledge/documents/KbUploadSourceDropdown.vue'
import { buildUploadFileName, folderPathExists } from '@nexus-web/core/components/knowledge/documents/folderTree'
import type { KnowledgeFolderTree } from '@nexus-web/core/api/knowledge-base/index'
import { useEnterpriseContext } from '../../stores/context'
import { listEnterpriseKnowledgeBases, type EnterpriseKnowledgeBase } from '@nexus-web/core/api/enterprise-knowledge'
import {
  deleteEnterpriseFaqEntry, deleteEnterpriseKnowledgeDocument, deleteEnterpriseWikiPage, downloadEnterpriseKnowledgeDocument,
  getEnterpriseWikiPage, listEnterpriseFaqEntries, listEnterpriseKnowledgeDocuments, listEnterpriseKnowledgeFolders, listEnterpriseWikiPages,
  createEnterpriseKnowledgeFolder, renameEnterpriseKnowledgeFolder,
  retryEnterpriseKnowledgeDocument, saveEnterpriseFaqEntry, saveEnterpriseWikiPage, uploadEnterpriseKnowledgeDocument,
  type EnterpriseFaqEntry, type EnterpriseKnowledgeDocument, type EnterpriseWikiPage, type FaqEntryInput, type WikiPageInput,
} from '@nexus-web/core/api/enterprise-knowledge-content'

const route = useRoute(), router = useRouter(), auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const kbId = computed(() => String(route.params.kbId || ''))
const canManage = computed(() => context.can('enterprise_kbs:manage'))
const knowledgeBase = ref<EnterpriseKnowledgeBase | null>(null)
const knowledgeBases = ref<EnterpriseKnowledgeBase[]>([])
const knowledgeOptions = computed(() => knowledgeBases.value.map(row => ({
  value: row.id, content: row.name, active: row.id === kbId.value,
})))
const loading = ref(false), working = ref(false), error = ref(''), ready = ref(false)
const keyword = ref(''), page = ref(1), pageSize = 20, total = ref(0)
const documents = ref<EnterpriseKnowledgeDocument[]>([]), faqEntries = ref<EnterpriseFaqEntry[]>([]), wikiPages = ref<EnterpriseWikiPage[]>([])
const uploadLabel = ref(''), uploadPercent = ref(0)
const folderTree = ref<KnowledgeFolderTree | null>(null), folder = ref(''), folderLoading = ref(false)
const folderCollapsed = ref(false), wikiTab = ref('pages')
const documentMode = computed(() => knowledgeBase.value?.type === 'document'
  || (knowledgeBase.value?.type === 'wiki' && wikiTab.value === 'documents'))
let rowsRequest = 0, foldersRequest = 0
const faqDialog = ref(false), faqSaving = ref(false), faqEditId = ref<string | null>(null)
const faqForm = ref({ standardQuestion: '', answers: '', similarQuestions: '', negativeQuestions: '', category: '', tagId: null as string | null, strategy: 'all' as 'all' | 'first', enabled: true, recommended: false })
const wikiDialog = ref(false), wikiLoading = ref(false), wikiSaving = ref(false), wikiEditSlug = ref<string | null>(null)
const wikiForm = ref({ slug: '', title: '', pageType: 'concept', status: 'published', summary: '', content: '', version: 0 })
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const statusLabel = (state: string) => t(`adminKnowledge.content.states.${state}`, state)

/** 只切换到当前企业目录中已确认可管理的知识库。 */
function switchKnowledgeBase({ value }: { value?: unknown }) {
  if (typeof value !== 'string' || value === kbId.value || !knowledgeBases.value.some(row => row.id === value)) return
  void router.push(`/knowledge/${encodeURIComponent(value)}/content`)
}

function reset() {
  epoch++; confirmation?.hide(); confirmation = undefined
  knowledgeBase.value = null; knowledgeBases.value = []; loading.value = false; working.value = false; error.value = ''; ready.value = false
  page.value = 1; total.value = 0; documents.value = []; faqEntries.value = []; wikiPages.value = []
  folderTree.value = null; folder.value = ''; folderLoading.value = false; folderCollapsed.value = false; wikiTab.value = 'pages'
  uploadLabel.value = ''; uploadPercent.value = 0; faqDialog.value = false; faqSaving.value = false; faqEditId.value = null
  wikiDialog.value = false; wikiLoading.value = false; wikiSaving.value = false; wikiEditSlug.value = null
}
function currentScope(current: number, scope: string, user: string, id: string) {
  return current === epoch && scope === tenant.value && user === String(auth.user?.id || '') && id === kbId.value && canManage.value
}
async function loadRows(current: number, scope: string, user: string, id: string) {
  if (!knowledgeBase.value) return
  const request = ++rowsRequest
  const active = () => request === rowsRequest && currentScope(current, scope, user, id)
  error.value = ''; loading.value = true
  try {
    const offset = (page.value - 1) * pageSize, query = keyword.value.trim()
    if (knowledgeBase.value.type === 'faq') {
      const result = await listEnterpriseFaqEntries(scope, id, query, offset, pageSize)
      if (!active()) return
      faqEntries.value = result.items; total.value = result.total
    } else if (knowledgeBase.value.type === 'wiki' && !documentMode.value) {
      const result = await listEnterpriseWikiPages(scope, id, query, page.value, pageSize)
      if (!active()) return
      wikiPages.value = result.items; total.value = result.total
    } else {
      const result = await listEnterpriseKnowledgeDocuments(scope, id, query, offset, pageSize, folder.value)
      if (!active()) return
      documents.value = result.items; total.value = result.total
    }
  } catch { if (active()) error.value = t('adminKnowledge.content.loadFailed') }
  finally { if (active()) loading.value = false }
}
async function load() {
  reset()
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = kbId.value
  if (!scope || !id || !canManage.value) { error.value = t('adminKnowledge.content.denied'); return }
  loading.value = true
  try {
    const rows = await listEnterpriseKnowledgeBases(scope)
    if (!currentScope(current, scope, user, id)) return
    const selected = rows.find(row => row.id === id && row.tenant_id === scope && row.can_manage)
    if (!selected) { error.value = t('adminKnowledge.content.denied'); return }
    knowledgeBases.value = rows.filter(row => row.tenant_id === scope && row.can_manage)
    knowledgeBase.value = selected; ready.value = true
    await Promise.all([loadRows(current, scope, user, id), refreshFolders()])
  } catch { if (currentScope(current, scope, user, id)) error.value = t('adminKnowledge.content.loadFailed') }
  finally { if (currentScope(current, scope, user, id)) loading.value = false }
}
function refreshSearch() { page.value = 1; const current = epoch; void loadRows(current, tenant.value, String(auth.user?.id || ''), kbId.value) }
function goToPage(next: number) { if (next < 1 || next > pageCount.value || next === page.value) return; page.value = next; void loadRows(epoch, tenant.value, String(auth.user?.id || ''), kbId.value) }
async function refreshFolders() {
  if (!documentMode.value) return
  const request = ++foldersRequest
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = kbId.value
  const active = () => request === foldersRequest && currentScope(current, scope, user, id)
  folderLoading.value = true
  try {
    const tree = await listEnterpriseKnowledgeFolders(scope, id)
    if (!active()) return
    folderTree.value = tree
    if (folder.value && !folderPathExists(tree.folders, folder.value)) selectFolder('')
  } catch {
    if (active()) folderTree.value = null
  } finally {
    if (active()) folderLoading.value = false
  }
}

function selectFolder(path: string) {
  if (working.value || folder.value === path) return
  folder.value = path
  refreshSearch()
}

async function createFolder(path: string) {
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = kbId.value
  const created = await createEnterpriseKnowledgeFolder(scope, id, path)
  if (!currentScope(current, scope, user, id)) return
  await refreshFolders()
  if (currentScope(current, scope, user, id)) selectFolder(created)
}

async function renameFolder({ from, to }: { from: string; to: string }) {
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = kbId.value
  if (working.value) return
  try {
    await renameEnterpriseKnowledgeFolder(scope, id, from, to)
    if (!currentScope(current, scope, user, id)) return
    if (folder.value === from || folder.value.startsWith(from + '/')) {
      folder.value = to + folder.value.slice(from.length)
    }
    await refreshFolders()
    if (currentScope(current, scope, user, id)) refreshSearch()
  } catch {
    if (currentScope(current, scope, user, id)) error.value = t('knowledgeBase.folderTree.renameFailed')
  }
}

function selectWikiTab(value: unknown) {
  if (working.value || (value !== 'pages' && value !== 'documents')) return
  wikiTab.value = value
  keyword.value = ''
  refreshSearch()
  void refreshFolders()
}

async function uploadFiles(files: File[]) {
  if (!files.length || !knowledgeBase.value || working.value) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = knowledgeBase.value.id
  const destination = folder.value, failed: string[] = []
  working.value = true; let uploaded = 0, deduplicated = 0
  for (const file of files) {
    if (!currentScope(current, scope, user, id)) break
    uploadLabel.value = file.name; uploadPercent.value = 0
    try {
      const result = await uploadEnterpriseKnowledgeDocument(scope, id, file, (loaded, totalBytes) => {
        if (currentScope(current, scope, user, id)) uploadPercent.value = Math.min(100, Math.floor(loaded / totalBytes * 100))
      }, buildUploadFileName(file, destination))
      if (!currentScope(current, scope, user, id)) return
      uploaded++; if (result.deduplicated) deduplicated++
    } catch { failed.push(file.name) }
  }
  if (!currentScope(current, scope, user, id)) return
  working.value = false; uploadLabel.value = ''; page.value = 1
  if (uploaded) void MessagePlugin.success(t('adminKnowledge.content.uploaded', { count: uploaded, deduplicated }))
  await Promise.all([loadRows(current, scope, user, id), refreshFolders()])
  if (failed.length && currentScope(current, scope, user, id)) {
    error.value = t('adminKnowledge.content.uploadFailed', { name: failed.join('、') })
  }
}
function download(row: EnterpriseKnowledgeDocument) {
  if (working.value || !knowledgeBase.value) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = knowledgeBase.value.id
  working.value = true
  void downloadEnterpriseKnowledgeDocument(scope, row.id).then(blob => {
    if (!currentScope(current, scope, user, id)) return
    const url = URL.createObjectURL(blob), anchor = document.createElement('a')
    anchor.href = url; anchor.download = row.filename; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 0)
  }).catch(() => { if (currentScope(current, scope, user, id)) error.value = t('adminKnowledge.content.downloadFailed') })
    .finally(() => { if (currentScope(current, scope, user, id)) working.value = false })
}
function confirmDelete(kind: 'document' | 'faq' | 'wiki', item: EnterpriseKnowledgeDocument | EnterpriseFaqEntry | EnterpriseWikiPage) {
  if (working.value || !knowledgeBase.value || (kind === 'wiki' && ['index', 'log'].includes((item as EnterpriseWikiPage).page_type))) return
  const name = kind === 'document' ? (item as EnterpriseKnowledgeDocument).filename : kind === 'faq' ? (item as EnterpriseFaqEntry).standard_question : (item as EnterpriseWikiPage).title
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = knowledgeBase.value.id
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminKnowledge.content.deleteTitle'), body: t('adminKnowledge.content.deleteConfirm', { name }), theme: 'danger',
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (!currentScope(current, scope, user, id) || working.value) return
      working.value = true; error.value = ''
      try {
        if (kind === 'document') await deleteEnterpriseKnowledgeDocument(scope, item.id)
        else if (kind === 'faq') await deleteEnterpriseFaqEntry(scope, id, item.id)
        else await deleteEnterpriseWikiPage(scope, id, (item as EnterpriseWikiPage).slug)
        if (!currentScope(current, scope, user, id)) return
        void MessagePlugin.success(t('adminKnowledge.content.deleted'))
        await Promise.all([loadRows(current, scope, user, id), refreshFolders()])
        if (page.value > pageCount.value) { page.value = pageCount.value; await loadRows(current, scope, user, id) }
      } catch { if (currentScope(current, scope, user, id)) error.value = t('adminKnowledge.content.deleteFailed') }
      finally { if (currentScope(current, scope, user, id)) working.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
function retryDocument(row: EnterpriseKnowledgeDocument) {
  if (working.value || !knowledgeBase.value) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = knowledgeBase.value.id
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminKnowledge.content.reindexTitle'), body: t('adminKnowledge.content.reindexConfirm', { name: row.filename }),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (!currentScope(current, scope, user, id) || working.value) return
      working.value = true; error.value = ''
      try { await retryEnterpriseKnowledgeDocument(scope, row.id); if (!currentScope(current, scope, user, id)) return; void MessagePlugin.success(t('adminKnowledge.content.reindexQueued')); await loadRows(current, scope, user, id) }
      catch { if (currentScope(current, scope, user, id)) error.value = t('adminKnowledge.content.reindexFailed') }
      finally { if (currentScope(current, scope, user, id)) working.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
function blankFaq() { faqEditId.value = null; faqForm.value = { standardQuestion: '', answers: '', similarQuestions: '', negativeQuestions: '', category: '', tagId: null, strategy: 'all', enabled: true, recommended: false }; faqDialog.value = true }
function editFaq(row: EnterpriseFaqEntry) { faqEditId.value = row.id; faqForm.value = { standardQuestion: row.standard_question, answers: row.answers.join('\n'), similarQuestions: row.similar_questions.join('\n'), negativeQuestions: row.negative_questions.join('\n'), category: row.category, tagId: row.tag_id, strategy: row.answer_strategy, enabled: row.is_enabled, recommended: row.is_recommended }; faqDialog.value = true }
function lines(value: string) { return value.split(/\r?\n/).map(item => item.trim()).filter(Boolean) }
async function saveFaq() {
  if (!knowledgeBase.value || faqSaving.value) return
  const input: FaqEntryInput = { standard_question: faqForm.value.standardQuestion, answers: lines(faqForm.value.answers), similar_questions: lines(faqForm.value.similarQuestions), negative_questions: lines(faqForm.value.negativeQuestions), category: faqForm.value.category, tag_id: faqForm.value.tagId, answer_strategy: faqForm.value.strategy, is_enabled: faqForm.value.enabled, is_recommended: faqForm.value.recommended }
  if (!input.standard_question.trim() || !input.answers.length) { error.value = t('adminKnowledge.content.faqRequired'); return }
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = knowledgeBase.value.id
  faqSaving.value = true; error.value = ''
  try { await saveEnterpriseFaqEntry(scope, id, input, faqEditId.value || undefined); if (!currentScope(current, scope, user, id)) return; faqDialog.value = false; void MessagePlugin.success(t('adminKnowledge.content.faqSaved')); await loadRows(current, scope, user, id) }
  catch { if (currentScope(current, scope, user, id)) error.value = t('adminKnowledge.content.faqSaveFailed') }
  finally { if (currentScope(current, scope, user, id)) faqSaving.value = false }
}
function blankWiki() { wikiEditSlug.value = null; wikiForm.value = { slug: '', title: '', pageType: 'concept', status: 'published', summary: '', content: '', version: 0 }; wikiDialog.value = true }
async function editWiki(row: EnterpriseWikiPage) {
  if (wikiLoading.value) return
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = row.knowledge_base_id
  wikiLoading.value = true; error.value = ''
  try { const detail = await getEnterpriseWikiPage(scope, id, row.slug); if (!currentScope(current, scope, user, id)) return; wikiEditSlug.value = row.slug; wikiForm.value = { slug: detail.slug, title: detail.title, pageType: detail.page_type, status: detail.status, summary: detail.summary, content: detail.content, version: detail.version }; wikiDialog.value = true }
  catch { if (currentScope(current, scope, user, id)) error.value = t('adminKnowledge.content.wikiLoadFailed') }
  finally { if (currentScope(current, scope, user, id)) wikiLoading.value = false }
}
async function saveWiki() {
  if (!knowledgeBase.value || wikiSaving.value) return
  if (!wikiForm.value.title.trim() || !wikiForm.value.slug.trim()) { error.value = t('adminKnowledge.content.wikiRequired'); return }
  const current = epoch, scope = tenant.value, user = String(auth.user?.id || ''), id = knowledgeBase.value.id
  const input: WikiPageInput = { slug: wikiForm.value.slug, title: wikiForm.value.title, page_type: wikiForm.value.pageType, status: wikiForm.value.status, summary: wikiForm.value.summary, content: wikiForm.value.content, ...(wikiEditSlug.value ? { version: wikiForm.value.version } : {}) }
  wikiSaving.value = true; error.value = ''
  try { await saveEnterpriseWikiPage(scope, id, input, wikiEditSlug.value || undefined); if (!currentScope(current, scope, user, id)) return; wikiDialog.value = false; void MessagePlugin.success(t('adminKnowledge.content.wikiSaved')); await loadRows(current, scope, user, id) }
  catch (failure) {
    const code = failure && typeof failure === 'object' && 'error' in failure && failure.error && typeof failure.error === 'object' && 'code' in failure.error ? failure.error.code : undefined
    if (currentScope(current, scope, user, id)) error.value = code === 'conflict' ? t('adminKnowledge.content.wikiConflict') : t('adminKnowledge.content.wikiSaveFailed')
  }
  finally { if (currentScope(current, scope, user, id)) wikiSaving.value = false }
}
watch([tenant, () => auth.user?.id, () => context.revision, canManage, kbId], () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(reset)
</script>

<template>
  <section class="knowledge-content-page">
    <header class="document-header">
      <nav :aria-label="t('adminKnowledge.content.title')">
        <h2 class="document-breadcrumb">
          <RouterLink class="breadcrumb-link" to="/knowledge">{{ t('consoleLayout.knowledgeManagement') }}</RouterLink>
          <t-icon name="chevron-right" class="breadcrumb-separator" aria-hidden="true" />
          <t-dropdown v-if="knowledgeBase" :options="knowledgeOptions" trigger="click" placement="bottom-left" @click="switchKnowledgeBase">
            <button type="button" class="breadcrumb-link breadcrumb-current" aria-haspopup="true">
              <span>{{ knowledgeBase.name }}</span><t-icon name="chevron-down" size="16px" aria-hidden="true" />
            </button>
          </t-dropdown>
          <span v-else>{{ t('adminKnowledge.content.title') }}</span>
        </h2>
      </nav>
      <p v-if="knowledgeBase?.description" class="document-subtitle">{{ knowledgeBase.description }}</p>
    </header>
    <t-alert v-if="error" theme="error" :message="error" />
    <t-alert v-if="uploadLabel" theme="info" :message="t('adminKnowledge.content.uploading', { name: uploadLabel, percent: uploadPercent })" />
    <t-alert v-if="knowledgeBase?.type === 'wiki'" theme="info" :message="t('adminKnowledge.content.wikiSourceHint')" />
    <t-tabs v-if="ready && knowledgeBase?.type === 'wiki'" :value="wikiTab" @change="selectWikiTab">
      <t-tab-panel value="pages" :label="t('adminKnowledge.content.titleColumn')" />
      <t-tab-panel value="documents" :label="t('knowledgeEditor.wikiBrowser.tabDocuments')" />
    </t-tabs>
    <KbDocumentLayout>
      <template #folders>
        <KbFolderTree v-if="ready && documentMode && !folderCollapsed" :tree="folderTree"
          :root-label="knowledgeBase?.name" :selected-path="folder" :loading="folderLoading"
          :can-edit="!working" :create-folder="createFolder" @select="selectFolder" @rename="renameFolder"
          @update:collapsed="folderCollapsed = $event" />
      </template>
    <div v-if="ready && knowledgeBase" class="content-toolbar">
      <t-button v-if="documentMode && folderCollapsed" variant="text"
        :aria-label="t('knowledgeBase.folderTree.expand')" @click="folderCollapsed = false">
        <template #icon><t-icon name="view-list" /></template>
      </t-button>
      <span v-if="documentMode" class="active-folder" :title="folder">{{ folder || t('knowledgeBase.folderTree.rootRow') }}</span>
      <t-input v-model="keyword" class="content-search" clearable :placeholder="t('adminKnowledge.content.search')" :aria-label="t('adminKnowledge.content.search')" @enter="refreshSearch">
        <template #prefix-icon><t-icon name="search" size="16px" /></template>
      </t-input>
      <t-button variant="outline" :disabled="loading || working" @click="refreshSearch">{{ t('adminKnowledge.content.search') }}</t-button>
      <div class="content-actions">
        <t-button variant="outline" :loading="loading" :disabled="working" @click="load">
          <template #icon><t-icon name="refresh" /></template>{{ t('connectionUi.refresh') }}
        </t-button>
        <t-button v-if="knowledgeBase.type === 'faq'" theme="primary" :disabled="working" @click="blankFaq">
          <template #icon><t-icon name="add" /></template>{{ t('adminKnowledge.content.addFaq') }}
        </t-button>
        <KbUploadSourceDropdown v-if="documentMode" :include-url="false" :disabled="working"
          trigger-icon="upload" :trigger-label="t('knowledgeBase.addDocument')"
          @files="uploadFiles" />
        <t-button v-if="knowledgeBase.type === 'wiki' && !documentMode" variant="outline" :disabled="working" @click="blankWiki">
          <template #icon><t-icon name="add" /></template>{{ t('adminKnowledge.content.addWiki') }}
        </t-button>
      </div>
    </div>
    <t-button v-else-if="error && canManage" class="content-retry" variant="outline" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button>
    <t-loading :loading="loading">
      <div v-if="knowledgeBase?.type === 'faq'" class="table-shell"><table><thead><tr><th>{{ t('adminKnowledge.content.question') }}</th><th>{{ t('adminKnowledge.content.answer') }}</th><th>{{ t('adminKnowledge.content.category') }}</th><th>{{ t('adminKnowledge.content.indexState') }}</th><th>{{ t('adminKnowledge.content.actions') }}</th></tr></thead><tbody><tr v-for="row in faqEntries" :key="row.id"><td>{{ row.standard_question }}</td><td>{{ row.answers.join(' / ') }}</td><td>{{ row.category || '—' }}</td><td><t-tag :theme="row.index_state === 'ready' ? 'success' : row.index_state === 'failed' ? 'danger' : 'warning'">{{ statusLabel(row.index_state) }}</t-tag></td><td class="row-actions"><t-button variant="text" :disabled="working" @click="editFaq(row)">{{ t('adminKnowledge.content.edit') }}</t-button><t-button variant="text" theme="danger" :disabled="working" @click="confirmDelete('faq', row)">{{ t('adminKnowledge.content.delete') }}</t-button></td></tr><tr v-if="!faqEntries.length && !loading"><td colspan="5" class="empty">{{ t('adminKnowledge.content.noFaq') }}</td></tr></tbody></table></div>
      <div v-else-if="knowledgeBase?.type === 'wiki' && !documentMode" class="table-shell"><table><thead><tr><th>{{ t('adminKnowledge.content.titleColumn') }}</th><th>{{ t('adminKnowledge.content.slug') }}</th><th>{{ t('adminKnowledge.content.wikiType') }}</th><th>{{ t('adminKnowledge.content.status') }}</th><th>{{ t('adminKnowledge.content.actions') }}</th></tr></thead><tbody><tr v-for="row in wikiPages" :key="row.id"><td>{{ row.title }}</td><td><code>{{ row.slug }}</code></td><td>{{ row.page_type }}</td><td>{{ row.status }}</td><td class="row-actions"><t-button variant="text" :disabled="working || ['index','log'].includes(row.page_type)" @click="editWiki(row)">{{ t('adminKnowledge.content.edit') }}</t-button><t-button variant="text" theme="danger" :disabled="working || ['index','log'].includes(row.page_type)" @click="confirmDelete('wiki', row)">{{ t('adminKnowledge.content.delete') }}</t-button></td></tr><tr v-if="!wikiPages.length && !loading"><td colspan="5" class="empty">{{ t('adminKnowledge.content.noWiki') }}</td></tr></tbody></table></div>
      <div v-else class="table-shell"><table><thead><tr><th>{{ t('adminKnowledge.content.filename') }}</th><th>{{ t('adminKnowledge.content.size') }}</th><th>{{ t('adminKnowledge.content.state') }}</th><th>{{ t('adminKnowledge.content.updated') }}</th><th>{{ t('adminKnowledge.content.actions') }}</th></tr></thead><tbody><tr v-for="row in documents" :key="row.id"><td><span class="filename">{{ row.filename }}</span><small v-if="row.latest_version?.error_message" class="row-error">{{ row.latest_version.error_message }}</small></td><td>{{ row.latest_version?.size ?? row.current_version?.size ?? 0 }} B</td><td><t-tag :theme="row.latest_version?.state === 'ready' ? 'success' : row.latest_version?.state === 'failed' ? 'danger' : 'warning'">{{ statusLabel(row.latest_version?.state || 'pending') }}</t-tag></td><td>{{ row.updated_at }}</td><td class="row-actions"><t-button variant="text" :disabled="working || !(row.latest_version || row.current_version)" @click="download(row)">{{ t('adminKnowledge.content.download') }}</t-button><t-button v-if="row.latest_version && ['failed','ready'].includes(row.latest_version.state)" variant="text" :disabled="working" @click="retryDocument(row)">{{ t(row.latest_version.state === 'failed' ? 'adminKnowledge.content.retry' : 'adminKnowledge.content.reindex') }}</t-button><t-button variant="text" theme="danger" :disabled="working" @click="confirmDelete('document', row)">{{ t('adminKnowledge.content.delete') }}</t-button></td></tr><tr v-if="!documents.length && !loading"><td colspan="5" class="empty">{{ t('adminKnowledge.content.noDocuments') }}</td></tr></tbody></table></div>
    </t-loading>
    <footer v-if="ready && total" class="pagination"><span>{{ t('adminKnowledge.content.total', { count: total }) }}</span><t-button variant="outline" :disabled="page <= 1 || loading || working" @click="goToPage(page - 1)">{{ t('adminKnowledge.content.previous') }}</t-button><span>{{ page }} / {{ pageCount }}</span><t-button variant="outline" :disabled="page >= pageCount || loading || working" @click="goToPage(page + 1)">{{ t('adminKnowledge.content.next') }}</t-button></footer>
    </KbDocumentLayout>
    <t-dialog :visible="faqDialog" :header="t(faqEditId ? 'adminKnowledge.content.editFaq' : 'adminKnowledge.content.addFaq')" width="min(680px, calc(100vw - 24px))" :confirm-btn="{ content: t('adminKnowledge.content.save'), loading: faqSaving, disabled: faqSaving }" :cancel-btn="{ content: t('common.cancel'), disabled: faqSaving }" :close-btn="!faqSaving" :close-on-overlay-click="!faqSaving" @confirm="saveFaq" @close="!faqSaving && (faqDialog = false)">
      <div class="editor-form"><label>{{ t('adminKnowledge.content.question') }}<t-input v-model="faqForm.standardQuestion" maxlength="1000" /></label><label>{{ t('adminKnowledge.content.answers') }}<t-textarea v-model="faqForm.answers" :autosize="{ minRows: 3, maxRows: 8 }" :placeholder="t('adminKnowledge.content.answersHint')" /></label><label>{{ t('adminKnowledge.content.similarQuestions') }}<t-textarea v-model="faqForm.similarQuestions" :autosize="{ minRows: 2, maxRows: 5 }" /></label><label>{{ t('adminKnowledge.content.negativeQuestions') }}<t-textarea v-model="faqForm.negativeQuestions" :autosize="{ minRows: 2, maxRows: 5 }" /></label><label>{{ t('adminKnowledge.content.category') }}<t-input v-model="faqForm.category" maxlength="160" /></label><label>{{ t('adminKnowledge.content.answerStrategy') }}<t-select v-model="faqForm.strategy" :options="[{label:t('adminKnowledge.content.allAnswers'),value:'all'},{label:t('adminKnowledge.content.firstAnswer'),value:'first'}]" /></label><div class="checks"><t-checkbox v-model="faqForm.enabled">{{ t('adminKnowledge.content.enabled') }}</t-checkbox><t-checkbox v-model="faqForm.recommended">{{ t('adminKnowledge.content.recommended') }}</t-checkbox></div></div>
    </t-dialog>
    <t-dialog :visible="wikiDialog" :header="t(wikiEditSlug ? 'adminKnowledge.content.editWiki' : 'adminKnowledge.content.addWiki')" width="min(760px, calc(100vw - 24px))" :confirm-btn="{ content: t('adminKnowledge.content.save'), loading: wikiSaving, disabled: wikiSaving }" :cancel-btn="{ content: t('common.cancel'), disabled: wikiSaving }" :close-btn="!wikiSaving" :close-on-overlay-click="!wikiSaving" @confirm="saveWiki" @close="!wikiSaving && (wikiDialog = false)">
      <div class="editor-form"><label>{{ t('adminKnowledge.content.slug') }}<t-input v-model="wikiForm.slug" :disabled="!!wikiEditSlug" maxlength="200" /></label><label>{{ t('adminKnowledge.content.titleColumn') }}<t-input v-model="wikiForm.title" maxlength="300" /></label><div class="two-columns"><label>{{ t('adminKnowledge.content.wikiType') }}<t-select v-model="wikiForm.pageType" :options="['concept','summary','entity','synthesis','comparison'].map(value => ({ label: value, value }))" /></label><label>{{ t('adminKnowledge.content.status') }}<t-select v-model="wikiForm.status" :options="[{label:t('adminKnowledge.content.published'),value:'published'},{label:t('adminKnowledge.content.draft'),value:'draft'}]" /></label></div><label>{{ t('adminKnowledge.content.summary') }}<t-textarea v-model="wikiForm.summary" :autosize="{ minRows: 2, maxRows: 4 }" maxlength="2000" /></label><label>{{ t('adminKnowledge.content.wikiBody') }}<t-textarea v-model="wikiForm.content" :autosize="{ minRows: 8, maxRows: 18 }" /></label><p v-if="wikiEditSlug" class="form-hint">{{ t('adminKnowledge.content.wikiVersion', { version: wikiForm.version }) }}</p></div>
    </t-dialog>
  </section>
</template>

<style scoped>
.knowledge-content-page { min-width: 0; min-height: 0; flex: 1; overflow-y: auto; padding: 20px 28px 24px; }
.document-header { margin-bottom: 16px; }
.document-breadcrumb { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; margin: 0; font-size: var(--app-text-4xl); font-weight: 600; line-height: 32px; }
.breadcrumb-link { display: inline-flex; align-items: center; gap: 6px; min-width: 0; max-width: 100%; padding: 0; color: inherit; background: none; border: 0; font: inherit; text-decoration: none; cursor: pointer; }
.breadcrumb-link:hover { color: var(--td-brand-color); }
.breadcrumb-link:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
.breadcrumb-current span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.breadcrumb-current :deep(.t-icon), .breadcrumb-separator { flex-shrink: 0; color: var(--td-text-color-placeholder); }
.document-subtitle { margin: 4px 0 0; color: var(--td-text-color-secondary); overflow-wrap: anywhere; }
.active-folder { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.content-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px 0; border-bottom: 1px solid var(--td-component-stroke); }
.content-search { width: 260px; max-width: 100%; }
.content-actions { margin-inline-start: auto; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.content-retry { margin-top: 12px; }
.table-shell { width: 100%; max-width: 100%; overflow-x: auto; margin-top: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); }
table { width: 100%; min-width: 760px; border-collapse: collapse; text-align: left; }
th, td { padding: 13px 16px; border-bottom: 1px solid var(--td-component-stroke); vertical-align: top; overflow-wrap: anywhere; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
tr:last-child td { border-bottom: 0; }
.row-actions { white-space: nowrap; }
.filename { overflow-wrap: anywhere; }
.row-error, .form-hint { display: block; margin-top: 6px; color: var(--td-error-color); white-space: pre-wrap; }
.empty { padding: 48px 16px; color: var(--td-text-color-secondary); text-align: center; }
.pagination { display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 20px; }
.editor-form { display: grid; gap: 16px; max-height: min(68vh, 720px); overflow-y: auto; padding: 2px; }
.editor-form label { display: grid; gap: 8px; color: var(--td-text-color-primary); }
.checks, .two-columns { display: flex; flex-wrap: wrap; gap: 16px; }
.two-columns > label { flex: 1; min-width: 180px; }
@media (max-width: 720px) {
  .knowledge-content-page { padding: 16px; }
  .content-actions { margin-inline-start: 0; }
  .pagination { flex-wrap: wrap; justify-content: center; }
}
</style>
