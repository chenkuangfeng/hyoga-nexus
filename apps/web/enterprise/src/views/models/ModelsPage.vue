<script setup lang="ts">
/** 企业模型卡片和操作按 WeKnora ModelSettings 组织。 */
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import { ADMIN_EDITOR_MODE, type EditorMode } from '@nexus-web/core/composables/useEditorPresentation'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  copyEnterpriseModel, deleteEnterpriseModel, listEnterpriseModelSettings,
  type EnterpriseModelSettings, type EnterpriseModelType, type ModelUsageCounts,
} from '@nexus-web/core/api/enterprise-models'
import { useEnterpriseContext } from '../../stores/context'
import ModelActions from './ModelActions.vue'
import ModelEditorDialog from './ModelEditorDialog.vue'
import ModelDebugDrawer from './ModelDebugDrawer.vue'
import { providerPresets } from './providerConfig'
import { modelLabel, modelTypeIcons, modelTypes, type ModelCard } from './modelTypes'

// 模型新增、编辑与调试沿用 WeKnora 的右侧抽屉。
provide(ADMIN_EDITOR_MODE, ref<EditorMode>('drawer'))

const auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.can('models:manage'))
const settings = ref<EnterpriseModelSettings | null>(null)
const loading = ref(false), busy = ref(false), loadFailed = ref(false), error = ref('')
const activeType = ref<EnterpriseModelType | 'all'>('all'), modelQuery = ref('')
const editor = ref<{ type: EnterpriseModelType; editing?: ModelCard } | null>(null)
const debug = ref(false)
const usageConflict = ref<{ name: string; counts: ModelUsageCounts } | null>(null)
let epoch = 0

const models = computed(() => settings.value?.providers.flatMap(provider => provider.models.map(model => ({ provider, model }))) ?? [])
const typeLabels = { chat: 'chat', embedding: 'embedding', rerank: 'rerank', vision: 'vllm', speech: 'asr' } as const
const typeTabs = computed(() => {
  const counts = { all: models.value.length, chat: 0, embedding: 0, rerank: 0, vision: 0, speech: 0 }
  for (const { model } of models.value) counts[model.model_type]++
  return [
    { value: 'all', label: t('common.all'), icon: 'view-module', count: counts.all },
    ...modelTypes.map(value => ({ value, label: t('modelSettings.typeShort.' + typeLabels[value]), icon: modelTypeIcons[value], count: counts[value] })),
  ]
})
const vendorIcons = new Map(providerPresets.map(preset => [preset.label, preset.icon]))
const query = computed(() => modelQuery.value.trim().toLowerCase())
const filteredModels = computed(() => models.value.filter(({ model, provider }) =>
  (activeType.value === 'all' || model.model_type === activeType.value)
  && [model.name, modelLabel(model), provider.name].some(name => name.toLowerCase().includes(query.value)),
))
const available = computed(() => settings.value !== null && !loading.value && !busy.value)

function invalidate() {
  epoch++
  editor.value = null
  debug.value = false
  usageConflict.value = null
  settings.value = null
  loading.value = busy.value = loadFailed.value = false
  error.value = ''
  activeType.value = 'all'
  modelQuery.value = ''
}

async function load() {
  if (!tenant.value || !canManage.value || loading.value) return
  const scope = epoch
  loading.value = true
  loadFailed.value = false
  try {
    const result = await listEnterpriseModelSettings(tenant.value)
    if (scope === epoch) settings.value = result
  } catch {
    if (scope === epoch) {
      settings.value = null
      loadFailed.value = true
    }
  } finally {
    if (scope === epoch) loading.value = false
  }
}

function openModel(editing?: ModelCard) {
  if (available.value) editor.value = { editing, type: activeType.value === 'all' ? 'chat' : activeType.value }
}

function modelSaved(type: EnterpriseModelType, editing: boolean) {
  editor.value = null
  if (!editing) {
    if (activeType.value !== 'all') activeType.value = type
    modelQuery.value = ''
  }
  void MessagePlugin.success(t(editing ? 'adminModels.modelVersionSaved' : 'adminModels.modelSaved'))
  void load()
}

async function changeModel(card: ModelCard, action: 'copy' | 'delete') {
  if (!available.value) return
  const scope = epoch, tenantId = tenant.value
  busy.value = true
  error.value = ''
  try {
    if (action === 'copy') {
      await copyEnterpriseModel(tenantId, card.provider.id, card.model.id, t('modelSettings.copySuffix').trim())
    } else {
      const counts = await deleteEnterpriseModel(tenantId, card.provider.id, card.model.id)
      if (counts) {
        if (scope === epoch) usageConflict.value = { name: modelLabel(card.model), counts }
        return
      }
    }
    if (scope !== epoch) return
    if (action === 'copy') modelQuery.value = ''
    void MessagePlugin.success(t(action === 'copy' ? 'modelSettings.toasts.copied' : 'modelSettings.toasts.deleted'))
    await load()
  } catch {
    if (scope === epoch) error.value = t(action === 'copy' ? 'modelSettings.toasts.copyFailed' : 'modelSettings.toasts.deleteFailed')
  } finally {
    if (scope === epoch) busy.value = false
  }
}

watch([tenant, () => auth.user?.id, () => context.revision, canManage], () => { invalidate(); void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(invalidate)
</script>

<template>
  <section class="model-settings">
    <header class="model-section-header">
      <div class="model-section-header__top">
        <div class="model-title">
          <h2>{{ t('modelSettings.title') }}</h2>
          <t-popup v-if="canManage" trigger="click" placement="bottom-left" show-arrow>
            <button type="button" class="model-title-help" :aria-label="t('adminModels.scopeHint')">
              <t-icon name="help-circle" size="16px" aria-hidden="true" />
            </button>
            <template #content><p class="model-hints">{{ t('adminModels.scopeHint') }}</p></template>
          </t-popup>
        </div>
        <div v-if="canManage" class="model-header-actions">
          <t-button variant="text" size="small" :disabled="!available || !models.length" @click="debug = true">
            <template #icon><t-icon name="play-circle" aria-hidden="true" /></template>
            {{ t('modelSettings.actions.debugModel') }}
          </t-button>
          <t-button variant="text" size="small" :disabled="!available" @click="openModel()">
            <template #icon><t-icon name="add" aria-hidden="true" /></template>
            {{ t('modelSettings.actions.addModel') }}
          </t-button>
        </div>
      </div>
      <p class="section-description">{{ t('adminModels.description') }}</p>
    </header>

    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error || loadFailed" theme="error" :message="error || t('adminModels.loadFailed')" />
      <t-button v-if="loadFailed" variant="text" @click="load">{{ t('connectionUi.refresh') }}</t-button>
      <div class="model-tabbar">
        <t-tabs v-model="activeType" class="model-type-tabs">
          <t-tab-panel v-for="tab in typeTabs" :key="tab.value" :value="tab.value">
            <template #label>
              <span class="model-type-tab">
                <t-icon :name="tab.icon" size="16px" aria-hidden="true" />
                <span>{{ tab.label }}</span>
                <span class="model-tab-count">{{ tab.count }}</span>
              </span>
            </template>
          </t-tab-panel>
        </t-tabs>
        <t-input v-model="modelQuery" class="model-search" clearable
          :placeholder="t('menu.search')" :aria-label="t('menu.search')">
          <template #prefix-icon><t-icon name="search" size="16px" aria-hidden="true" /></template>
        </t-input>
      </div>

      <t-loading :loading="loading" size="small" class="model-list">
        <div v-if="settings && query && !filteredModels.length" class="empty-state">
          <t-empty :description="t('common.noResult')" />
          <t-button variant="outline" @click="modelQuery = ''">{{ t('common.clear') }}</t-button>
        </div>
        <div v-else-if="settings" class="model-grid">
          <article v-for="card in filteredModels" :key="card.model.id" class="model-card" :class="'model-card--' + card.model.model_type">
            <div class="model-card__badge"><t-icon :name="modelTypeIcons[card.model.model_type]" size="16px" aria-hidden="true" /></div>
            <div class="model-card__body">
              <div class="model-card__header">
                <h3 class="model-card__title">
                  <button type="button" class="model-card__edit" :title="modelLabel(card.model)" :disabled="!available"
                    @click="openModel(card)">{{ modelLabel(card.model) }}</button>
                </h3>
                <div class="model-card__actions">
                  <ModelActions :label="t('common.expand')" :disabled="!available" :actions="[
                    { label: t('common.edit'), key: 'edit', run: () => openModel(card) },
                    { label: t('common.copy'), key: 'copy', run: () => changeModel(card, 'copy') },
                  ]" />
                  <t-popconfirm :content="t('modelSettings.confirmDelete', { name: modelLabel(card.model) })"
                    :confirm-btn="{ content: t('common.delete'), theme: 'danger' }"
                    :cancel-btn="{ content: t('common.cancel') }" placement="bottom-right"
                    @confirm="changeModel(card, 'delete')">
                    <t-button theme="danger" variant="text" shape="square" size="small" :disabled="!available"
                      :aria-label="t('common.delete')" :title="t('common.delete')">
                      <template #icon><t-icon name="delete" aria-hidden="true" /></template>
                    </t-button>
                  </t-popconfirm>
                </div>
              </div>
              <p class="model-card__subtitle">
                <span class="model-card__vendor" :title="card.provider.name">
                  <img v-if="vendorIcons.has(card.provider.name)" :src="vendorIcons.get(card.provider.name)" alt="" />
                  <span>{{ card.provider.name }}</span>
                </span>
                <span v-if="card.model.display_name && card.model.display_name !== card.model.name" class="model-card__upstream"
                  :title="card.model.name">· {{ card.model.name }}</span>
              </p>
            </div>
          </article>
          <button type="button" class="model-card model-card--add" :disabled="!available" @click="openModel()">
            <span class="model-card--add__icon" aria-hidden="true"><t-icon name="add" /></span>
            <span class="model-card--add__label">{{ t('modelSettings.actions.addModel') }}</span>
          </button>
        </div>
      </t-loading>
    </template>

    <ModelEditorDialog v-if="editor" :tenant="tenant" :initial-type="editor.type" :editing="editor.editing"
      @close="editor = null" @saved="modelSaved" />
    <ModelDebugDrawer v-if="debug" :tenant="tenant" :models="models" @close="debug = false" />
    <t-dialog :visible="!!usageConflict" :header="t('modelSettings.usage.title')" :footer="false"
      @update:visible="(value: boolean) => { if (!value) usageConflict = null }">
      <template v-if="usageConflict">
        <p>{{ t('modelSettings.usage.description', { name: usageConflict.name }) }}</p>
        <ul>
          <li v-if="usageConflict.counts.agents">{{ t('modelSettings.usage.agents', { count: usageConflict.counts.agents }) }}</li>
          <li v-if="usageConflict.counts.knowledge_bases">{{ t('modelSettings.usage.knowledgeBases', { count: usageConflict.counts.knowledge_bases }) }}</li>
          <li v-if="usageConflict.counts.memory">{{ t('modelSettings.usage.longTermMemory') }}（{{ usageConflict.counts.memory }}）</li>
        </ul>
      </template>
    </t-dialog>
  </section>
</template>

<style scoped lang="less">
@import './ModelsPage.reference.less';
</style>
