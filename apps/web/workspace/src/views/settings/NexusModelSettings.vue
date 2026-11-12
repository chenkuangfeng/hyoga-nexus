<template>
  <!--
    Settings → Models on Nexus (openspec 2026-11-05-weknora-agent-tool-model-settings; spec model-management R5).
    Layout and classes follow WeKnora `views/settings/ModelSettings.vue`: type tabs with counts, search,
    a card grid and an "add model" card. Data comes from `GET /tenants/{id}/model-settings`.
    Omitted WeKnora parts: built-in models, model catalog, debug drawer, usage dialog, Ollama and cloud sources.
  -->
  <div class="model-settings">
    <div class="section-header">
      <div class="section-header__top">
        <div class="model-title">
          <h2>{{ $t('modelSettings.title') }}</h2>
        </div>
        <div class="model-header-actions">
          <t-button theme="default" variant="text" size="small" class="model-header-action" @click="openAdd">
            <template #icon><add-icon /></template>
            {{ $t('modelSettings.actions.addModel') }}
          </t-button>
        </div>
      </div>
      <p class="section-description">{{ $t('nexusModels.description') }}</p>
    </div>

    <div class="model-tabbar">
      <t-tabs v-model="activeType" class="model-type-tabs">
        <t-tab-panel v-for="tab in typeTabs" :key="tab.value" :value="tab.value">
          <template #label>
            <span class="model-type-tab">
              <t-icon :name="tab.icon" size="16px" />
              <span>{{ tab.label }}</span>
              <span class="model-tab-count">{{ tab.count }}</span>
            </span>
          </template>
        </t-tab-panel>
      </t-tabs>
      <t-input v-model="query" class="model-search" :placeholder="$t('menu.search')" :aria-label="$t('menu.search')" clearable>
        <template #prefix-icon><t-icon name="search" size="16px" /></template>
      </t-input>
    </div>

    <t-alert v-if="loadError" theme="error" :message="loadError" />

    <div class="model-list">
      <t-loading :loading="loading" size="small" class="model-list-loading">
        <div v-if="!loading && visibleCards.length === 0 && query.trim()" class="empty-state">
          <t-empty :description="$t('common.noResult')" />
          <t-button variant="outline" @click="query = ''">{{ $t('common.clear') }}</t-button>
        </div>
        <div v-else-if="!loading" class="model-grid">
          <div v-for="card in visibleCards" :key="card.key" class="model-card"
            :class="[`model-card--${weknoraType(card.type)}`, { 'model-card--clickable': card.canManage }]"
            :role="card.canManage ? 'button' : undefined" :tabindex="card.canManage ? 0 : undefined"
            @click="card.canManage && openEdit(card)" @keydown.enter="card.canManage && openEdit(card)">
            <div class="model-card__badge" :aria-label="typeLabel(card.type)">
              <t-icon :name="typeIcon(card.type)" size="16px" />
            </div>
            <div class="model-card__body">
              <div class="model-card__header">
                <h3 class="model-card__title" :title="card.model.name">{{ card.model.name }}</h3>
                <div class="model-card__actions" @click.stop>
                  <t-dropdown :options="menuOptions(card)" placement="bottom-right" attach="body" trigger="click"
                    @click="(data: any) => handleMenu(String(data.value), card)">
                    <t-button variant="text" shape="square" size="small" class="model-card__action-btn model-card__more">
                      <t-icon name="ellipsis" />
                    </t-button>
                  </t-dropdown>
                  <t-popconfirm v-if="card.canManage" :content="$t('nexusModels.confirmDelete', { name: card.model.name })"
                    :confirm-btn="{ content: $t('common.delete'), theme: 'danger' }" :cancel-btn="{ content: $t('common.cancel') }"
                    placement="bottom-right" @confirm="removeModel(card)">
                    <t-tooltip :content="$t('common.delete')" placement="top">
                      <t-button theme="danger" shape="square" variant="text" size="small"
                        class="model-card__action-btn model-card__delete" @click.stop>
                        <template #icon><t-icon name="delete" /></template>
                      </t-button>
                    </t-tooltip>
                  </t-popconfirm>
                </div>
              </div>
              <p class="model-card__subtitle">
                <span class="model-card__vendor"><span>{{ card.provider.name }}</span></span>
                <span class="model-card__sep">·</span>
                <span>{{ $t(`nexusModels.scope.${card.provider.scope}`) }}</span>
                <template v-for="scope in card.defaultScopes" :key="scope">
                  <span class="model-card__sep">·</span>
                  <t-tag size="small" theme="primary" variant="light">{{ $t(`nexusModels.defaultTag.${scope}`) }}</t-tag>
                </template>
              </p>
            </div>
          </div>
          <button type="button" class="model-card model-card--add" @click="openAdd">
            <span class="model-card--add__icon" aria-hidden="true"><add-icon /></span>
            <span class="model-card--add__label">{{ $t('modelSettings.actions.addModel') }}</span>
          </button>
        </div>
      </t-loading>
    </div>

    <NexusModelEditorDialog v-if="tenantId && settings" v-model:visible="dialogVisible" :tenant-id="tenantId"
      :settings="settings" :editing="editing" :initial-type="activeType === 'all' ? 'chat' : activeType" @saved="reload" />
  </div>
</template>

<script setup lang="ts">
/**
 * Lists the caller's visible models in the active space and manages them through the Nexus
 * model-settings API. Only management of personal providers, or of space providers for space
 * administrators, is offered; the server rechecks every write.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import { AddIcon } from 'tdesign-icons-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  deleteModel, getModelSettings, setDefaultModel, testSavedConnection,
  type ModelScope, type ModelSettingsView, type NexusModelType,
} from '@nexus-web/core/api/nexus-models'
import { countByType, filterCards, flattenModelCards, NEXUS_TYPES, type ModelCard } from './nexusModelCards'
import NexusModelEditorDialog from './NexusModelEditorDialog.vue'

const { t } = useI18n()
const authStore = useAuthStore()

const tenantId = computed(() => authStore.effectiveTenantId ? String(authStore.effectiveTenantId) : '')
const settings = ref<ModelSettingsView | null>(null)
const loading = ref(false)
const loadError = ref('')
const activeType = ref<NexusModelType | 'all'>('all')
const query = ref('')
const dialogVisible = ref(false)
const editing = ref<ModelCard | null>(null)

const cards = computed(() => settings.value ? flattenModelCards(settings.value) : [])
const visibleCards = computed(() => filterCards(cards.value, activeType.value, query.value))

const TYPE_ICON: Record<NexusModelType, string> = {
  chat: 'chat', embedding: 'chart-bubble', rerank: 'filter-sort', vision: 'image', speech: 'sound',
}
/** WeKnora's short type labels and card modifiers use `vllm` / `asr` for vision / speech. */
function weknoraType(type: NexusModelType): string {
  return type === 'vision' ? 'vllm' : type === 'speech' ? 'asr' : type
}
function typeIcon(type: NexusModelType): string { return TYPE_ICON[type] }
function typeLabel(type: NexusModelType): string { return t(`modelSettings.typeShort.${weknoraType(type)}`) }

const typeTabs = computed(() => {
  const counts = countByType(cards.value)
  return [
    { value: 'all' as const, label: t('common.all'), icon: 'view-module', count: counts.all },
    ...NEXUS_TYPES.map(value => ({ value, label: typeLabel(value), icon: typeIcon(value), count: counts[value] })),
  ]
})

function errorMessage(error: unknown, fallback: string): string {
  const message = error && typeof error === 'object' ? (error as { message?: unknown }).message : undefined
  return typeof message === 'string' && message ? message : fallback
}

async function reload() {
  if (!tenantId.value) return
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await getModelSettings(tenantId.value)
  } catch (error) {
    loadError.value = errorMessage(error, t('nexusModels.loadFailed'))
  } finally {
    loading.value = false
  }
}

watch(tenantId, () => { void reload() }, { immediate: true })

function openAdd() {
  editing.value = null
  dialogVisible.value = true
}

function openEdit(card: ModelCard) {
  editing.value = card
  dialogVisible.value = true
}

/** Card menu: edit and test for managers; default toggles per scope (space defaults need admin). */
function menuOptions(card: ModelCard) {
  const options: Array<{ content: string; value: string }> = []
  if (card.canManage) {
    options.push({ content: t('common.edit'), value: 'edit' })
    if (card.type === 'chat') options.push({ content: t('model.editor.testConnection'), value: 'test' })
  }
  const scopes: ModelScope[] = settings.value?.can_manage_tenant && card.provider.scope === 'tenant'
    ? ['personal', 'tenant'] : ['personal']
  for (const scope of scopes) {
    const isDefault = card.defaultScopes.includes(scope)
    options.push({
      content: t(isDefault ? `nexusModels.clearDefault.${scope}` : `nexusModels.setDefault.${scope}`),
      value: `${isDefault ? 'clear' : 'set'}-default-${scope}`,
    })
  }
  return options
}

async function handleMenu(value: string, card: ModelCard) {
  if (value === 'edit') return openEdit(card)
  if (value === 'test') return testModel(card)
  const match = value.match(/^(set|clear)-default-(personal|tenant)$/)
  if (!match) return
  try {
    await setDefaultModel(tenantId.value, match[2] as ModelScope, card.type, match[1] === 'set' ? card.model.version_id : null)
    MessagePlugin.success(t('nexusModels.defaultSaved'))
    await reload()
  } catch (error) {
    MessagePlugin.error(errorMessage(error, t('nexusModels.saveFailed')))
  }
}

async function testModel(card: ModelCard) {
  try {
    const result = await testSavedConnection(tenantId.value, card.provider.id, card.model.id)
    if (result.ok) MessagePlugin.success(result.message || t('model.editor.connectionSuccess'))
    else MessagePlugin.error(`${result.message || t('model.editor.connectionFailed')}${result.code ? `（${result.code}）` : ''}`)
  } catch (error) {
    MessagePlugin.error(errorMessage(error, t('model.editor.connectionFailed')))
  }
}

async function removeModel(card: ModelCard) {
  try {
    await deleteModel(tenantId.value, card.provider.id, card.model.id)
    MessagePlugin.success(t('nexusModels.deleted'))
    await reload()
  } catch (error) {
    MessagePlugin.error(errorMessage(error, t('nexusModels.saveFailed')))
  }
}
</script>

<!-- Copied from WeKnora views/settings/ModelSettings.vue -->
<style lang="less" scoped>
@import (reference) '@/components/css/provider-card.less';
@import (reference) '@/components/css/settings-section.less';

.model-settings {
  width: 100%;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  color: var(--td-text-color-primary);
  container-type: inline-size;
}

.section-header {
  .settings-section-header();
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
  flex-shrink: 0;

  &__top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    // 为设置弹窗右上角的关闭按钮留出空间。
    padding-right: 32px;
  }

  h2 {
    margin: 0;
  }

}

.model-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.model-title-help {
  .settings-title-help();
}

.model-header-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.model-header-action.t-button {
  flex-shrink: 0;
  min-height: 32px;
  padding: 0 12px;
  gap: 6px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-sm);
  background: var(--td-bg-color-container);
  color: var(--td-text-color-primary);
  font-size: var(--app-text-md);

  &:hover:not(:disabled) {
    background: var(--td-bg-color-container-hover);
  }

  &:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: 2px;
  }

  :deep(.t-icon) {
    color: var(--td-brand-color);
  }
}

.builtin-models-hint {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: min(320px, calc(100vw - 64px));
  padding: 4px;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-sm);
  line-height: 20px;
}

.builtin-hint-label {
  margin: 0;
  color: var(--td-text-color-primary);
  font-weight: 500;
}

.builtin-hint-text {
  margin: 0;
}

.builtin-models-hint .doc-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--td-brand-color);
  text-decoration: none;

  &:hover { text-decoration: underline; }
}

.model-tabbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
  border-bottom: 1px solid var(--td-component-stroke);
}

.model-type-tabs {
  flex: 1;
  min-width: 0;
  background: transparent;

  :deep(.t-tabs__nav-container) { background: transparent; }
  :deep(.t-tabs__nav-container.t-is-top::after) { display: none; }
  :deep(.t-tabs__nav-item) {
    height: 44px;
    padding: 0;
    margin-right: 24px;
    font-size: var(--app-text-base);
    font-weight: 500;
    color: var(--td-text-color-secondary);

    &:last-child { margin-right: 0; }
    &:hover { background: transparent; color: var(--td-text-color-primary); }
  }
  :deep(.t-tabs__nav-item-wrapper) { padding: 0 2px; margin: 0; }
  :deep(.t-tabs__nav-item:not(.t-is-disabled):hover .t-tabs__nav-item-wrapper) { background: transparent; }
  :deep(.t-tabs__bar) { display: none; }
  :deep(.t-tabs__nav-item.t-is-active) {
    color: var(--td-text-color-primary);
    text-shadow: none;
    &::after {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 2px;
      border-radius: var(--app-radius-pill);
      background: var(--td-brand-color);
    }
    .t-icon { color: var(--td-brand-color); }
    .model-tab-count {
      background: var(--td-brand-color-light);
      color: var(--td-brand-color);
    }
  }
  :deep(.t-tabs__operations) { display: none; }
  :deep(.t-tabs__nav-scroll) {
    overflow-x: auto;
    scrollbar-width: none;
    &::-webkit-scrollbar { display: none; }
  }
  :deep(.t-tabs__content) { display: none; }
}

.model-type-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.model-tab-count {
  min-width: 20px;
  height: 20px;
  box-sizing: border-box;
  padding: 0 6px;
  border-radius: var(--app-radius-pill);
  background: var(--td-bg-color-secondarycontainer);
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-xs);
  font-weight: 500;
  line-height: 20px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.model-search {
  flex: 0 0 240px;
  width: 240px;
  :deep(.t-input) { border-radius: var(--app-radius-sm); }
}

.model-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--app-space-4) 0 var(--app-space-8);
}

.model-list-loading {
  display: block;
  min-height: 120px;
}

.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
  gap: 10px;
  align-items: stretch;

  .model-card--add { width: 100%; height: 100%; }
}

@container (max-width: 900px) {
  .model-tabbar { flex-wrap: wrap; gap: 0; }
  .model-type-tabs { flex-basis: 100%; }
  .model-search { flex: 1 1 100%; width: 100%; margin: 8px 0; }
}

// 模型卡片沿用工具箱的紧凑间距、圆角和悬浮反馈。
.model-card {
  .provider-card();
  align-items: center;
  min-height: 88px;
  padding: 12px;
  gap: 10px;
  box-sizing: border-box;
  border-radius: var(--app-radius-md);

  &--add {
    .provider-card-add();
    min-height: 88px;
    gap: 6px;

    &:hover,
    &:focus-visible {
      box-shadow: none;
    }

    &__icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: var(--app-radius-md);
      background: var(--td-bg-color-secondarycontainer);
      color: var(--td-text-color-secondary);
      font-size: var(--app-text-2xl);
    }

    &__label {
      font-size: var(--app-text-md);
      font-weight: 500;
      line-height: 1.4;
    }
  }

  &--clickable {
    .provider-card-interactive();

    &:hover {
      border-color: color-mix(in srgb, var(--td-brand-color) 40%, var(--td-component-stroke));
      box-shadow: 0 3px 12px color-mix(in srgb, var(--td-text-color-primary) 6%, transparent);
    }
  }
}

.model-card__badge {
  .provider-card-badge(28px, 8px);
  .provider-card-badge-color(#0052d9);
}

// 5 种类型的徽章配色 —— 比原 tag 配色饱和度低一档，避免炫光
.model-card--chat .model-card__badge {
  .provider-card-badge-color(#0052d9);
}

.model-card--embedding .model-card__badge {
  .provider-card-badge-color(#6235bb);
}

.model-card--rerank .model-card__badge {
  .provider-card-badge-color(#b85c00);
}

.model-card--vllm .model-card__badge {
  .provider-card-badge-color(#c93e3e);
}

.model-card--asr .model-card__badge {
  .provider-card-badge-color(#118053);
}

.model-card__body {
  .provider-card-body();
}

.model-card__header {
  .provider-card-header();
}

.model-card__title {
  .provider-card-title();
}

/*
  Built-in lock indicator. Most cards in a typical install ARE built-in,
  so loud styling everywhere becomes noise — instead the lock is muted
  and small by default, and lights up on hover. The signal that matters
  to users is "which models did I add" → user-added cards stand out by
  the absence of the lock.
*/
.model-card__lock {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  color: var(--td-text-color-placeholder);
  opacity: 0.6;
  transition: color var(--app-motion-fast) ease, opacity var(--app-motion-fast) ease;

  .t-icon {
    font-size: var(--app-text-md);
  }
}

.model-card:hover .model-card__lock {
  opacity: 1;
  color: var(--td-text-color-secondary);
}

.model-card__subtitle {
  // A flex row, not inline text: .model-card__vendor is an inline-flex box
  // whose baseline comes from its first item — the 14px icon, whose baseline
  // is its bottom edge — so as inline content it sat a couple of pixels off
  // the "· 200K" beside it. Aligning the row by centre instead of by
  // baseline puts every part of the line on one optical line.
  display: flex;
  align-items: center;
  min-width: 0;
  margin: 2px 0 0;
  font-size: var(--app-text-sm);
  line-height: 1.5;
  color: var(--td-text-color-secondary);
}

.model-card__vendor {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;

  // The vendor name is the only part long enough to need truncating; the
  // context window and the badges after it must stay readable.
  > span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.model-card__sep,
.model-card__ctx,
.model-card__vision {
  flex: none;
  white-space: nowrap;
}

.model-card__vendor-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  border-radius: var(--app-radius-xs);
  object-fit: contain;
}

.model-card__sep {
  margin: 0 4px;
  color: var(--td-text-color-placeholder);
}

.model-card__vision {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.model-card__ctx {
  font-variant-numeric: tabular-nums;
}

.model-card__ctx--default {
  color: var(--td-text-color-placeholder);
}

.model-card__actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 2px;
}

.model-card__action-btn {
  flex-shrink: 0;
  padding: 2px;
  opacity: 0;
  transition: opacity var(--app-motion-fast) ease;
}

.model-card__more {
  color: var(--td-text-color-placeholder);

  &:hover,
  &:focus-visible {
    background: var(--td-bg-color-secondarycontainer);
    color: var(--td-text-color-primary);
  }
}

// Hover / 键盘焦点 时显示操作按钮，避免静态卡片上有"杂物"。
.model-card:hover .model-card__action-btn,
.model-card:focus-within .model-card__action-btn,
.model-card__actions:focus-within .model-card__action-btn {
  opacity: 1;
}

.empty-state {
  padding: 64px 0;
  text-align: center;

  :deep(.t-empty__description) {
    font-size: var(--app-text-base);
    color: var(--td-text-color-placeholder);
    margin-bottom: 16px;
  }
}

.model-usage-dialog__description {
  margin: 0 0 16px;
  color: var(--td-text-color-secondary);
  line-height: 1.6;
}

.model-usage-dialog__content {
  max-height: min(58vh, 560px);
  overflow-y: auto;
  padding-right: 4px;
}

.model-usage-group {
  & + & {
    margin-top: 20px;
  }

  h3 {
    margin: 0 0 8px;
    font-size: var(--app-text-base);
    font-weight: 600;
    color: var(--td-text-color-primary);
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
    border: 1px solid var(--td-component-stroke);
    border-radius: var(--app-radius-md);
    overflow: hidden;
  }

  li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;

    & + li {
      border-top: 1px solid var(--td-component-stroke);
    }
  }
}

.model-usage-truncated {
  margin: 8px 0 0;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
  line-height: 1.5;
}

.model-usage-resource {
  min-width: 0;

  strong {
    display: block;
    margin-bottom: 6px;
    overflow: hidden;
    color: var(--td-text-color-primary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.model-usage-bindings {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.model-usage-memory {
  padding: 10px 12px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);
}

.model-usage-dialog__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}
</style>
