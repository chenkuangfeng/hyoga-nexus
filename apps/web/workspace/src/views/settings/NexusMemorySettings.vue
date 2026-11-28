<template>
  <div class="memory-settings">
    <div class="section-header">
      <h2>{{ t('memorySettings.title') }}</h2>
      <p class="section-description">{{ t('nexusMemory.myDescription') }}</p>
    </div>

    <p v-if="loadError" class="load-error" role="alert">{{ loadError }}</p>

    <div class="memory-list-wrapper">
      <div class="memory-toolbar">
        <t-button theme="primary" :disabled="busy" @click="addVisible = true">{{ t('memorySettings.addTitle') }}</t-button>
      </div>
      <t-tabs v-model="tab" class="memory-tabs">
        <t-tab-panel value="active" :label="t('nexusMemory.tabActive', { count: entries.length })">
          <p v-if="!entries.length" class="empty">{{ t('nexusMemory.emptyActive') }}</p>
          <div v-for="entry in entries" :key="entry.id" class="memory-card" :class="{ 'is-disabled': !entry.enabled }">
            <div class="card-head">
              <span class="kind-tag">{{ kindLabel(entry.kind) }}</span>
              <span class="entry-title">{{ entry.title }}</span>
              <span class="meta">v{{ entry.version }} · {{ t('nexusMemory.importance') }} {{ entry.importance }}</span>
              <span v-if="entry.topic" class="meta">· {{ entry.topic }}</span>
            </div>
            <div class="card-body">{{ entry.content }}</div>
            <div class="card-actions">
              <label class="inline-label">{{ t('nexusMemory.enabled') }}</label>
              <t-switch :value="entry.enabled" size="small" :disabled="busy"
                @change="(value: boolean) => setAvailability(entry, { enabled: value })" />
              <t-date-picker :value="entry.valid_until ? entry.valid_until.slice(0, 10) : ''" size="small" clearable
                :placeholder="t('nexusMemory.validUntil')"
                @change="(value: unknown) => setAvailability(entry, { valid_until: typeof value === 'string' && value ? `${value}T23:59:59Z` : null })" />
              <t-button v-if="entry.version > 1" size="small" variant="text" :disabled="busy" @click="restore(entry)">
                {{ t('nexusMemory.restorePrevious') }}
              </t-button>
              <t-popconfirm :content="t('nexusMemory.archiveConfirm')" @confirm="archive(entry)">
                <t-button size="small" variant="text" theme="danger" :disabled="busy">{{ t('nexusMemory.archive') }}</t-button>
              </t-popconfirm>
            </div>
          </div>
        </t-tab-panel>

        <t-tab-panel value="pending" :label="t('nexusMemory.tabPending', { count: drafts.length })">
          <p v-if="!drafts.length" class="empty">{{ t('nexusMemory.emptyPending') }}</p>
          <div v-for="draft in drafts" :key="draft.id" class="memory-card">
            <div class="card-head">
              <span class="kind-tag">{{ kindLabel(draft.kind) }}</span>
              <span class="origin">{{ t(`nexusMemory.origin.${originKey(draft.origin)}`) }}</span>
              <span v-if="draft.target_entry_id" class="target">
                {{ t('nexusMemory.editsEntry', { title: entryTitle(draft.target_entry_id) }) }}
              </span>
            </div>
            <div class="card-body">{{ draft.diff }}</div>
            <p v-if="draft.fact_identity.subject || draft.fact_identity.attribute || draft.fact_identity.scope" class="hint-line">
              {{ t('nexusMemory.factIdentity') }}：{{ [draft.fact_identity.subject, draft.fact_identity.attribute, draft.fact_identity.scope].filter(Boolean).join(' · ') }}
            </p>
            <ul v-if="draft.evidence.length" class="evidence">
              <li v-for="(quote, index) in draft.evidence" :key="index">“{{ quote.quote }}”</li>
            </ul>
            <p v-if="draft.merges.length" class="hint-line">
              {{ t('nexusMemory.mergeHint', { titles: draft.merges.map(m => m.title).join('、') }) }}
            </p>
            <p v-if="draft.conflicts.length" class="hint-line is-warning">
              {{ t('agentStream.memoryDraft.conflictHint', { titles: draft.conflicts.map(h => h.title).join('、') }) }}
            </p>
            <p v-if="draft.similar.length" class="hint-line is-warning">
              {{ t('agentStream.memoryDraft.similarHint', { titles: draft.similar.map(h => h.title).join('、') }) }}
            </p>
            <p v-if="draft.same_topic_candidates.length || draft.identity_candidates.length" class="hint-line is-warning">
              {{ t('nexusMemory.candidateOnlyHint', { titles: [...draft.identity_candidates, ...draft.same_topic_candidates].map(h => h.title).join('、') }) }}
            </p>
            <div class="card-actions">
              <t-input v-model="titles[draft.id]" size="small" :maxlength="160" class="title-input"
                :placeholder="t('agentStream.memoryDraft.titlePlaceholder')" />
              <t-select v-model="importances[draft.id]" size="small" class="importance-select"
                :label="t('nexusMemory.importance')">
                <t-option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level" :label="String(level)" />
              </t-select>
              <t-button size="small" variant="outline" :disabled="busy" @click="review(draft, false)">
                {{ t('agentStream.memoryDraft.reject') }}
              </t-button>
              <t-button size="small" theme="primary" :disabled="busy" @click="review(draft, true)">
                {{ t('agentStream.memoryDraft.publish') }}
              </t-button>
            </div>
          </div>
        </t-tab-panel>

        <t-tab-panel value="auto_proposed" :label="t('nexusMemory.tabAutoProposed', { count: topics.length })">
          <p v-if="!topics.length" class="empty">{{ t('nexusMemory.emptyTopics') }}</p>
          <div v-for="topic in topics" :key="topic.id" class="memory-card">
            <div class="card-head">
              <span class="entry-title">{{ topic.topic }}</span>
              <span class="meta">{{ t('nexusMemory.topicHits', { hits: topic.hits, threshold: topic.threshold }) }}</span>
              <span v-if="topic.promoted" class="kind-tag">{{ t('nexusMemory.topicPromoted') }}</span>
            </div>
            <p v-if="topic.aliases.length" class="hint-line">{{ topic.aliases.join('、') }}</p>
          </div>
        </t-tab-panel>


        <t-tab-panel value="archived" :label="t('nexusMemory.tabArchived', { count: archivedEntries.length })">
          <p v-if="!archivedEntries.length" class="empty">{{ t('nexusMemory.archivedEmpty') }}</p>
          <div v-for="entry in archivedEntries" :key="entry.id" class="memory-card is-disabled">
            <div class="card-head">
              <span class="kind-tag">{{ kindLabel(entry.kind) }}</span>
              <span class="entry-title">{{ entry.title }}</span>
              <span class="meta">v{{ entry.version }}</span>
            </div>
            <div class="card-body">{{ entry.content }}</div>
          </div>
        </t-tab-panel>
      </t-tabs>
      <t-dialog v-model:visible="addVisible" :header="t('memorySettings.addTitle')"
        :confirm-btn="{ content: t('agentStream.memoryDraft.publish'), loading: busy }"
        :cancel-btn="{ disabled: busy }" :close-on-overlay-click="false" :close-on-esc-keydown="!busy" :close-btn="!busy"
        :on-confirm="createMemory" :on-cancel="() => { if (!busy) addVisible = false }">
        <t-form label-align="top" @submit="createMemory">
          <t-form-item :label="t('agentStream.memoryDraft.titlePlaceholder')" required>
            <t-input v-model="newMemory.title" :maxlength="160" :disabled="busy" />
          </t-form-item>
          <t-form-item :label="t('memorySettings.addKindLabel')" required>
            <t-select v-model="newMemory.kind" :disabled="busy">
              <t-option v-for="kind in memoryKinds" :key="kind" :value="kind" :label="kindLabel(kind)" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('memorySettings.addContentLabel')" required>
            <t-textarea v-model="newMemory.content" :maxlength="8000" :disabled="busy" :autosize="{ minRows: 4, maxRows: 10 }" />
          </t-form-item>
          <t-form-item :label="t('nexusMemory.importance')">
            <t-select v-model="newMemory.importance" :disabled="busy">
              <t-option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level" :label="String(level)" />
            </t-select>
          </t-form-item>
          <p v-if="createError" role="alert" class="load-error">{{ createError }}</p>
        </t-form>
      </t-dialog>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useI18n } from 'vue-i18n'
import { memoryErrorText } from './memoryError'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  archiveMemoryEntry, createManualMemory, listMemory, listMemoryTopics, restoreMemoryVersion,
  reviewMemoryDraftWith, setMemoryAvailability, type MemoryDraft, type MemoryEntry, type MemoryTopic,
} from '@nexus-web/core/api/nexus-memory'

const { t } = useI18n()
const authStore = useAuthStore()
const tenant = () => authStore.effectiveTenantId || ''
const memoryKinds = ['fact', 'preference', 'personal_info', 'interest', 'task'] as const
const entries = ref<MemoryEntry[]>([])
const archivedEntries = ref<MemoryEntry[]>([])
const drafts = ref<MemoryDraft[]>([])
const topics = ref<MemoryTopic[]>([])
const titles = reactive<Record<string, string>>({})
const importances = reactive<Record<string, number>>({})
const tab = ref('active')
const addVisible = ref(false)
const createError = ref('')
const busy = ref(false)
const loadError = ref('')
const newMemory = reactive({ title: '', kind: 'fact' as typeof memoryKinds[number], content: '', importance: 3 })

const kindLabel = (kind: string) => t(`nexusMemory.kinds.${kindLabelKey(kind)}`)
function kindLabelKey(kind: string): string {
  if (kind === 'profile') return 'personal_info'
  if (kind === 'memory' || kind === 'sop') return 'fact'
  return (memoryKinds as readonly string[]).includes(kind) ? kind : 'fact'
}
const originKey = (origin: string) => (['capture', 'background', 'foreground'].includes(origin) ? origin : 'foreground')
const entryTitle = (id: string) => entries.value.find(entry => entry.id === id)?.title || id.slice(0, 8)
function errorText(error: unknown): string { return memoryErrorText(error, t('agentStream.memoryDraft.failed')) }

async function loadLists() {
  const listed = await listMemory(tenant())
  entries.value = listed.entries
  archivedEntries.value = listed.archived
  drafts.value = listed.drafts
  for (const draft of listed.drafts) {
    titles[draft.id] ??= draft.target_entry_id ? entryTitle(draft.target_entry_id) : (draft.topic || draft.diff.slice(0, 20))
    importances[draft.id] ??= draft.importance ?? 3
  }
  topics.value = await listMemoryTopics(tenant())
}
async function load() {
  if (!tenant()) return
  try { await loadLists() } catch { loadError.value = t('nexusMemory.loadFailed') }
}
async function run(action: () => Promise<unknown>, success?: string) {
  busy.value = true
  try {
    await action()
    if (success) MessagePlugin.success(success)
    await loadLists()
  } catch (error) { MessagePlugin.error(errorText(error)) }
  finally { busy.value = false }
}
async function review(draft: MemoryDraft, approve: boolean) {
  const title = (titles[draft.id] || '').trim()
  if (approve && !title) { MessagePlugin.warning(t('agentStream.memoryDraft.titleRequired')); return }
  await run(() => reviewMemoryDraftWith(tenant(), draft.id, {
    approve, title, ...(approve ? { importance: importances[draft.id] } : {}),
  }), approve ? t('agentStream.memoryDraft.published') : t('agentStream.memoryDraft.rejected'))
}
async function createMemory() {
  if (busy.value) return
  createError.value = ''
  if (!newMemory.title.trim() || !newMemory.content.trim()) { createError.value = t('agentStream.memoryDraft.titleRequired'); return }
  busy.value = true
  try {
    await createManualMemory(tenant(), { ...newMemory, title: newMemory.title.trim(), content: newMemory.content.trim() })
    addVisible.value = false
    Object.assign(newMemory, { title: '', kind: 'fact', content: '', importance: 3 })
    tab.value = 'active'
    MessagePlugin.success(t('agentStream.memoryDraft.published'))
    await loadLists()
  } catch (error) { createError.value = errorText(error); MessagePlugin.error(createError.value) }
  finally { busy.value = false }
}
async function setAvailability(entry: MemoryEntry, change: { enabled?: boolean; valid_until?: string | null }) {
  await run(() => setMemoryAvailability(tenant(), entry.id, change))
}
async function restore(entry: MemoryEntry) {
  await run(() => restoreMemoryVersion(tenant(), entry.id, entry.version - 1, entry.version), t('nexusMemory.restored'))
}
async function archive(entry: MemoryEntry) {
  await run(() => archiveMemoryEntry(tenant(), entry.id), t('nexusMemory.archived'))
}
onMounted(load)
</script>

<style lang="less" scoped>
@import (reference) '@/components/css/settings-section.less';

.memory-settings {
  width: 100%;
}

.section-header {
  .settings-section-header();
}

.settings-group {
  display: flex;
  flex-direction: column;
}

.setting-row {
  .setting-row();
}

.setting-info {
  .setting-info();
}

.setting-control {
  .setting-control();
}

.notice {
  padding: 10px 14px;
  margin-bottom: 8px;
  border-radius: var(--app-radius-md);
  background: var(--td-warning-color-1);
  color: var(--td-text-color-primary);
}

.load-error {
  color: var(--td-error-color);
}

.memory-tabs {
  margin-top: 16px;
}

.memory-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.empty {
  padding: 24px 0;
  text-align: center;
  color: var(--td-text-color-placeholder);
}

.memory-card {
  padding: 12px 14px;
  margin-top: 10px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);

  &.is-disabled {
    opacity: 0.6;
  }
}

.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: var(--app-text-md);
}

.kind-tag {
  padding: 0 6px;
  border-radius: var(--app-radius-sm);
  font-size: var(--app-text-sm);
  background: var(--td-bg-color-secondarycontainer);
  color: var(--td-text-color-secondary);
}

.entry-title {
  font-weight: 500;
  color: var(--td-text-color-primary);
}

.origin,
.target,
.meta {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
}

.card-body {
  margin-top: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--td-text-color-primary);
}

.evidence {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
}

.hint-line {
  margin: 4px 0 0;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);

  &.is-warning {
    color: var(--td-warning-color);
  }
}

.card-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.title-input {
  flex: 1 1 200px;
  min-width: 0;
}

.importance-select {
  width: 120px;
}

.inline-label {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
}
</style>
