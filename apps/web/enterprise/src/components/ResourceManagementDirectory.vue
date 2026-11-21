<script setup lang="ts" generic="T extends { name: string; created_at?: string; updated_at?: string }">
/** 企业资源目录外壳，沿用 WeKnora 的标题区、搜索工具栏和资源网格。 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ResourceCatalogIcon from './ResourceCatalogIcon.vue'
import ResourceSortControl from '@nexus-web/core/components/ResourceSortControl.vue'
import { DEFAULT_RESOURCE_SORT, sortResourceItems } from '@nexus-web/core/utils/resourceSorting'

const props = defineProps<{
  title: string
  description: string
  scopeHint: string
  resource: 'agent' | 'knowledge'
  createLabel: string
  searchLabel: string
  emptyLabel: string
  allowed: boolean
  loading: boolean
  ready: boolean
  disabled: boolean
  error: string
  total: number
  items: T[]
}>()
const query = defineModel<string>('query', { required: true })
const emit = defineEmits<{ create: []; refresh: [] }>()
const { t } = useI18n()
const sort = ref(DEFAULT_RESOURCE_SORT)
const displayedItems = computed(() => sortResourceItems(props.items, sort.value, {
  getName: item => item.name,
  getCreatedAt: item => item.created_at,
  getUpdatedAt: item => item.updated_at,
}))
</script>

<template>
  <section class="resource-management-directory">
    <header class="header">
      <div class="header-title">
        <div class="title-row">
          <h2><ResourceCatalogIcon :kind="resource" :size="24" />{{ title }}</h2>
          <div v-if="allowed" class="header-actions">
            <ResourceSortControl v-model="sort" />
            <t-button variant="text" theme="default" size="small" class="header-action-btn" :disabled="!ready || disabled" @click="emit('create')">
              <template #icon>
                <t-icon v-if="resource === 'knowledge'" name="folder-add" size="16px" />
                <ResourceCatalogIcon v-else kind="agent" :size="19" />
              </template>{{ createLabel }}
            </t-button>
            <t-tooltip :content="t('connectionUi.refresh')" placement="bottom">
              <t-button variant="text" theme="default" size="small" shape="square" class="header-action-btn refresh-button"
                :aria-label="t('connectionUi.refresh')" :loading="loading" :disabled="disabled" @click="emit('refresh')">
                <template #icon><t-icon name="refresh" size="16px" /></template>
              </t-button>
            </t-tooltip>
          </div>
        </div>
        <p class="header-subtitle">{{ description }}</p>
      </div>
    </header>

    <t-alert v-if="!allowed" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <div class="resource-toolbar">
        <div class="scope-filters">
          <span class="scope-label" :title="scopeHint">{{ t('listSpaceSidebar.all') }} <span v-if="ready" class="scope-count">{{ total }}</span></span>
          <slot name="toolbar" />
        </div>
        <t-input v-model="query" class="search-input" clearable :aria-label="searchLabel" :placeholder="searchLabel">
          <template #prefix-icon><t-icon name="search" size="16px" /></template>
        </t-input>
      </div>

      <div class="directory-main" :aria-busy="loading">
        <t-alert v-if="error" theme="error" :message="error" />
        <div v-if="loading && !ready" class="resource-grid" aria-hidden="true">
          <div v-for="index in 6" :key="index" class="skeleton-card is-skeleton">
            <div class="card-header"><t-skeleton animation="gradient" :row-col="[[{ width: '28px', height: '28px', type: 'circle' }, { width: '40%', height: '18px' }]]" /></div>
            <div class="card-content"><t-skeleton animation="gradient" :row-col="[{ width: '100%', height: '14px' }, { width: '70%', height: '14px' }]" /></div>
            <div class="card-bottom"><t-skeleton animation="gradient" :row-col="[[{ width: '60px', height: '22px' }]]" /></div>
          </div>
        </div>
        <div v-else-if="ready && displayedItems.length" class="resource-grid">
          <slot :items="displayedItems" />
        </div>
        <div v-else-if="ready && !error" class="resource-empty">
          <t-icon v-if="query.trim()" name="search" size="32px" aria-hidden="true" />
          <ResourceCatalogIcon v-else :kind="resource" :size="32" />
          <p>{{ query.trim() ? t('common.noResult') : emptyLabel }}</p>
          <t-button v-if="query.trim()" variant="outline" @click="query = ''">{{ t('common.clear') }}</t-button>
          <t-button v-else theme="primary" :disabled="disabled" @click="emit('create')">
            <template #icon>
              <t-icon v-if="resource === 'knowledge'" name="folder-add" size="16px" />
              <ResourceCatalogIcon v-else kind="agent" :size="18" />
            </template>{{ createLabel }}
          </t-button>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped lang="less">
@import (reference) '@nexus-web/core/styles/resource-card.less';

.resource-management-directory {
  .resource-list-content();
  .resource-list-header();
}

.header-title { display: flex; flex-direction: column; }
.title-row, .header-actions, .header h2 { display: flex; align-items: center; gap: 8px; }
.header h2 { margin: 0 auto 0 0; font-size: var(--app-text-4xl); font-weight: 600; line-height: 32px; }
.header-subtitle { margin: 0; line-height: 20px; }
.header-actions { flex-wrap: wrap; max-width: 100%; }
.header-action-btn { border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); display: inline-flex; align-items: center; cursor: pointer; }
.header .header-action-btn.refresh-button { width: 32px; padding: 0; justify-content: center; }
.resource-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--app-space-3);
  flex-shrink: 0;
  padding-bottom: var(--app-space-3);
  border-bottom: 1px solid var(--td-component-stroke);
}
.scope-filters { display: flex; align-items: center; flex-wrap: wrap; gap: var(--app-space-3); }
.scope-label {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  padding: 3px 12px;
  min-height: 32px;
  border-radius: var(--app-radius-sm);
  background: var(--td-bg-color-secondarycontainer);
  font-size: var(--app-text-md);
}
.scope-count { font-size: var(--app-text-xs); font-variant-numeric: tabular-nums; color: var(--td-text-color-secondary); }
.search-input { width: 260px; max-width: 100%; margin-inline-start: auto; }
.directory-main { .resource-list-main(); }
.resource-grid { .resource-card-grid(); }
.skeleton-card { .resource-card(); .resource-card-quiet(); }
.skeleton-card :deep(.t-skeleton) { flex: 1; min-width: 0; }
.resource-empty { display: grid; justify-items: center; gap: 10px; padding: 48px 12px; text-align: center; color: var(--td-text-color-secondary); }
.resource-empty p { margin: 0; }

@media (max-width: 720px) { .search-input { width: 100%; } }
</style>
