<template>
  <!-- "My memory" on the Nexus API (openspec 2026-11-05-memory-switches 2.3; 2026-11-06-memory-evolution 2.8, 3.6,
       5.5, 6.2). Layout and class names follow WeKnora MemorySettings.vue; WeKnora features Nexus does not have
       (memory documents, export, clear, manual add) are not offered. -->
  <div class="memory-settings">
    <div class="section-header">
      <h2>{{ t('memorySettings.title') }}</h2>
      <p class="section-description">{{ t('nexusMemory.myDescription') }}</p>
    </div>

    <p v-if="loadError" class="load-error" role="alert">{{ loadError }}</p>

    <template v-if="prefs">
      <div v-if="prefs.reason === 'space_disabled'" class="notice" role="status">{{ t('nexusMemory.spaceDisabled') }}</div>

      <div class="settings-group">
        <div class="setting-row">
          <div class="setting-info">
            <label>{{ t('nexusMemory.personalSwitch') }}</label>
            <p class="desc">{{ t('nexusMemory.personalSwitchDesc') }}</p>
          </div>
          <div class="setting-control">
            <t-switch :value="prefs.memory_enabled" :disabled="prefs.reason === 'space_disabled' || busy"
              @change="togglePersonal" />
          </div>
        </div>

        <!-- Nexus extension: automatic extraction is chosen per member, with the member's own model. -->
        <div class="setting-row">
          <div class="setting-info">
            <label>{{ t('nexusMemory.captureLabel') }}</label>
            <p class="desc">
              {{ prefs.write_mode === 'explicit' ? t('nexusMemory.captureExplicit') : t('nexusMemory.captureDesc') }}
            </p>
          </div>
          <div class="setting-control">
            <t-switch :value="capture.enabled" :disabled="prefs.write_mode === 'explicit' || !capture.model_profile_version_id || busy"
              @change="(value: boolean) => saveCapture({ enabled: value })" />
          </div>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <label>{{ t('nexusMemory.captureModel') }}</label>
            <p class="desc">{{ t('nexusMemory.captureModelDesc') }}</p>
          </div>
          <div class="setting-control" style="min-width: 260px">
            <t-select :value="capture.model_profile_version_id || undefined" :disabled="busy"
              :placeholder="t('nexusMemory.chooseModel')"
              @change="(value: unknown) => saveCapture({ model_profile_version_id: typeof value === 'string' ? value : null })">
              <t-option v-for="model in chatModels" :key="model.version_id" :value="model.version_id" :label="model.name" />
            </t-select>
          </div>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <label>{{ t('nexusMemory.capacityLabel') }}</label>
            <p class="desc">{{ t('nexusMemory.capacityDesc') }}</p>
          </div>
          <div class="setting-control">
            <t-radio-group :value="capture.capacity_policy" :disabled="busy"
              @change="(value: unknown) => saveCapture({ capacity_policy: value === 'evict_auto' ? 'evict_auto' : 'reject' })">
              <t-radio-button value="reject">{{ t('nexusMemory.capacityReject') }}</t-radio-button>
              <t-radio-button value="evict_auto">{{ t('nexusMemory.capacityEvict') }}</t-radio-button>
            </t-radio-group>
          </div>
        </div>

        <div v-if="usage" class="setting-row">
          <div class="setting-info">
            <label>{{ t('nexusMemory.usageLabel', { days: usage.days }) }}</label>
            <p class="desc">{{ t('nexusMemory.usageDesc', { calls: usage.calls, tokens: usageTokens }) }}</p>
          </div>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <label>{{ t('nexusMemory.consolidateLabel') }}</label>
            <p class="desc">{{ t('nexusMemory.consolidateDesc') }}</p>
          </div>
          <div class="setting-control">
            <t-button variant="outline" :loading="consolidating" :disabled="!capture.model_profile_version_id"
              @click="consolidate">{{ t('nexusMemory.consolidate') }}</t-button>
          </div>
        </div>
      </div>

      <t-tabs v-model="tab" class="memory-tabs">
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

        <t-tab-panel value="active" :label="t('nexusMemory.tabActive', { count: entries.length })">
          <p v-if="!entries.length" class="empty">{{ t('nexusMemory.emptyActive') }}</p>
          <div v-for="entry in entries" :key="entry.id" class="memory-card" :class="{ 'is-disabled': !entry.enabled }">
            <div class="card-head">
              <span class="kind-tag">{{ kindLabel(entry.kind) }}</span>
              <span class="entry-title">{{ entry.title }}</span>
              <span class="meta">v{{ entry.version }} · {{ t('nexusMemory.importance') }} {{ entry.importance }}</span>
              <span v-if="entry.topic" class="meta">· {{ entry.topic }}</span>
            </div>
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

        <t-tab-panel value="topics" :label="t('nexusMemory.tabTopics', { count: topics.length })">
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

        <t-tab-panel value="affinity" :label="t('nexusMemory.tabAffinity', { count: affinity.length })">
          <p class="hint-line">{{ t('nexusMemory.affinityHint') }}</p>
          <p v-if="!affinity.length" class="empty">{{ t('nexusMemory.emptyAffinity') }}</p>
          <div v-for="item in affinity" :key="item.document_id" class="memory-card">
            <div class="card-head">
              <span class="entry-title">{{ item.filename }}</span>
              <span class="meta">{{ t('nexusMemory.affinityHits', { hits: item.hits }) }}</span>
              <span v-if="item.boost > 1" class="kind-tag">{{ t('nexusMemory.affinityBoost', { boost: item.boost.toFixed(2) }) }}</span>
              <t-popconfirm :content="t('nexusMemory.affinityClearConfirm')" @confirm="clearAffinity(item.document_id)">
                <t-button size="small" variant="text" theme="danger" :disabled="busy">{{ t('nexusMemory.affinityClear') }}</t-button>
              </t-popconfirm>
            </div>
          </div>
          <t-popconfirm v-if="affinity.length" :content="t('nexusMemory.affinityClearAllConfirm')" @confirm="clearAffinity()">
            <t-button size="small" variant="outline" theme="danger" :disabled="busy">{{ t('nexusMemory.affinityClearAll') }}</t-button>
          </t-popconfirm>
        </t-tab-panel>

        <t-tab-panel value="archived" :label="t('nexusMemory.tabArchived')">
          <p class="empty">{{ t('nexusMemory.archivedPlanned') }}</p>
        </t-tab-panel>
      </t-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  archiveMemoryEntry, getCaptureSettings, getCaptureUsage, getMemoryPreferences, listMemory, listMemoryDocAffinity, listMemoryTopics, clearMemoryDocAffinity,
  requestConsolidation, restoreMemoryVersion, reviewMemoryDraftWith, setMemoryAvailability, updateCaptureSettings,
  updateMemoryPreferences, type CaptureSettings, type CaptureUsage, type MemoryDraft, type MemoryEntry,
  type MemoryDocAffinity, type MemoryPreferences, type MemoryTopic,
} from '@nexus-web/core/api/nexus-memory'
import { getModelSettings, type NexusModel } from '@nexus-web/core/api/nexus-models'

const { t } = useI18n()
const authStore = useAuthStore()
const tenant = () => authStore.effectiveTenantId || ''

const prefs = ref<MemoryPreferences | null>(null)
const capture = reactive<CaptureSettings>({ enabled: false, model_profile_version_id: null, capacity_policy: 'reject' })
const usage = ref<CaptureUsage | null>(null)
const chatModels = ref<NexusModel[]>([])
const entries = ref<MemoryEntry[]>([])
const drafts = ref<MemoryDraft[]>([])
const topics = ref<MemoryTopic[]>([])
const affinity = ref<MemoryDocAffinity[]>([])
const titles = reactive<Record<string, string>>({})
const importances = reactive<Record<string, number>>({})
const tab = ref('pending')
const busy = ref(false)
const consolidating = ref(false)
const loadError = ref('')

const usageTokens = computed(() => {
  const value = usage.value?.usage
  if (!value) return 0
  return value.total_tokens ?? (value.input_tokens ?? 0) + (value.output_tokens ?? 0)
})

const kindLabel = (kind: string) => t(`agentStream.memoryDraft.kinds.${['memory', 'sop', 'profile'].includes(kind) ? kind : 'memory'}`)
  + (kind === 'interest' ? ` · ${t('nexusMemory.interest')}` : '')
const originKey = (origin: string) => (['capture', 'background', 'foreground'].includes(origin) ? origin : 'foreground')
const entryTitle = (id: string) => entries.value.find(entry => entry.id === id)?.title || id.slice(0, 8)

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : t('agentStream.memoryDraft.failed')
}

async function loadLists() {
  const listed = await listMemory(tenant())
  entries.value = listed.entries
  drafts.value = listed.drafts
  for (const draft of listed.drafts) {
    titles[draft.id] ??= draft.target_entry_id ? entryTitle(draft.target_entry_id) : (draft.topic || draft.diff.slice(0, 20))
    importances[draft.id] ??= draft.importance ?? 3
  }
  topics.value = await listMemoryTopics(tenant())
  affinity.value = await listMemoryDocAffinity(tenant())
}

/** Clear one document's counter, or every counter when no id is given. */
async function clearAffinity(documentId?: string) {
  await run(() => clearMemoryDocAffinity(tenant(), documentId), t('nexusMemory.affinityCleared'))
}

async function load() {
  if (!tenant()) return
  try {
    prefs.value = await getMemoryPreferences(tenant())
    Object.assign(capture, await getCaptureSettings(tenant()))
    await loadLists()
  } catch {
    loadError.value = t('nexusMemory.loadFailed')
    return
  }
  try { usage.value = await getCaptureUsage(tenant()) } catch { usage.value = null }
  try {
    const models = await getModelSettings(tenant())
    chatModels.value = models.providers.flatMap(p => p.models).filter(m => m.model_type === 'chat')
  } catch { chatModels.value = [] }
}

async function run(action: () => Promise<unknown>, success?: string) {
  busy.value = true
  try {
    await action()
    if (success) MessagePlugin.success(success)
    await loadLists()
  } catch (error) {
    MessagePlugin.error(errorText(error))
  } finally {
    busy.value = false
  }
}

async function togglePersonal(value: boolean) {
  await run(() => updateMemoryPreferences(tenant(), value))
  prefs.value = await getMemoryPreferences(tenant())
}

async function saveCapture(change: Partial<CaptureSettings>) {
  const next = { ...capture, ...change }
  // Enabling capture needs a model; choosing a model alone keeps capture off until the switch is turned on.
  if (next.enabled && !next.model_profile_version_id) next.enabled = false
  await run(async () => {
    await updateCaptureSettings(tenant(), next)
    Object.assign(capture, next)
  })
}

async function review(draft: MemoryDraft, approve: boolean) {
  const title = (titles[draft.id] || '').trim()
  if (approve && !title) {
    MessagePlugin.warning(t('agentStream.memoryDraft.titleRequired'))
    return
  }
  await run(() => reviewMemoryDraftWith(tenant(), draft.id, {
    approve, title, ...(approve ? { importance: importances[draft.id] } : {}),
  }), approve ? t('agentStream.memoryDraft.published') : t('agentStream.memoryDraft.rejected'))
}

async function setAvailability(entry: MemoryEntry, change: { enabled?: boolean; valid_until?: string | null }) {
  await run(() => setMemoryAvailability(tenant(), entry.id, change))
}

async function restore(entry: MemoryEntry) {
  await run(() => restoreMemoryVersion(tenant(), entry.id, entry.version - 1, entry.version),
    t('nexusMemory.restored'))
}

async function archive(entry: MemoryEntry) {
  await run(() => archiveMemoryEntry(tenant(), entry.id), t('nexusMemory.archived'))
}

async function consolidate() {
  consolidating.value = true
  try {
    await requestConsolidation(tenant())
    MessagePlugin.success(t('nexusMemory.consolidateQueued'))
  } catch (error) {
    const status = (error as { status?: number })?.status
    MessagePlugin.error(status === 409 ? t('nexusMemory.consolidateRefused') : errorText(error))
  } finally {
    consolidating.value = false
  }
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
