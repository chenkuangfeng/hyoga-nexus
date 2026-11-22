<script setup lang="ts">
/** 工具栏共用目录导航、搜索和视图切换，筛选和上传动作由宿主提供。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { folderBreadcrumbs } from './folderTree'

const props = defineProps<{
  name?: string
  path: string
  treeCollapsed?: boolean
  loading?: boolean
  filtering?: boolean
}>()
const keyword = defineModel<string>('keyword', { required: true })
const viewMode = defineModel<'list' | 'grid'>('viewMode', { required: true })
const emit = defineEmits<{ search: []; 'open-folder': [path: string]; 'expand-tree': [] }>()
const { t } = useI18n()
const crumbs = computed(() => folderBreadcrumbs(props.path))
</script>

<template>
  <div class="doc-filter-bar">
    <nav class="doc-folder-path" :aria-label="t('knowledgeBase.folderTree.title')">
      <button v-if="treeCollapsed" type="button" class="doc-folder-path__tree-toggle"
        :aria-expanded="false" :title="t('knowledgeBase.folderTree.expand')"
        :aria-label="t('knowledgeBase.folderTree.expand')"
        @click="emit('expand-tree')">
        <t-icon name="view-list" size="16px" />
      </button>
      <button v-if="crumbs.length" type="button" class="doc-folder-path__crumb" :title="name" @click="emit('open-folder', '')">
        {{ name }}
      </button>
      <span v-else class="doc-folder-path__crumb is-current" :title="name" aria-current="page">{{ name }}</span>
      <template v-for="(crumb, index) in crumbs" :key="crumb.path">
        <t-icon name="chevron-right" class="doc-folder-path__sep" />
        <span v-if="index === crumbs.length - 1" class="doc-folder-path__crumb is-current" :title="crumb.name" aria-current="page">{{ crumb.name }}</span>
        <button v-else type="button" class="doc-folder-path__crumb" :title="crumb.name" @click="emit('open-folder', crumb.path)">{{ crumb.name }}</button>
      </template>
      <span v-if="!loading" class="doc-folder-path__count">
        <slot name="count" />
      </span>
      <t-tooltip v-if="filtering" :content="t('knowledgeBase.folderTree.searchingSubtree')">
        <t-icon name="info-circle" class="doc-folder-path__sep" />
      </t-tooltip>
    </nav>
    <div class="doc-filter-bar__trailing">
      <t-input v-model.trim="keyword" :placeholder="t('knowledgeBase.docSearchPlaceholder')"
        :aria-label="t('knowledgeBase.docSearchPlaceholder')" clearable class="doc-search-input" @clear="emit('search')"
        @enter="emit('search')">
        <template #prefix-icon>
          <t-icon name="search" size="16px" />
        </template>
      </t-input>
      <slot name="controls" />
      <div class="doc-view-toggle" role="group" :aria-label="t('knowledgeBase.viewModeToggle')">
        <t-tooltip :content="t('knowledgeBase.viewModeGrid')" placement="top">
          <button type="button" class="doc-view-toggle-btn" :class="{ active: viewMode === 'grid' }"
            :aria-label="t('knowledgeBase.viewModeGrid')" @click="viewMode = 'grid'" :aria-pressed="viewMode === 'grid'">
            <t-icon name="view-module" size="16px" />
          </button>
        </t-tooltip>
        <t-tooltip :content="t('knowledgeBase.viewModeList')" placement="top">
          <button type="button" class="doc-view-toggle-btn" :class="{ active: viewMode === 'list' }"
            :aria-label="t('knowledgeBase.viewModeList')" @click="viewMode = 'list'" :aria-pressed="viewMode === 'list'">
            <t-icon name="view-list" size="16px" />
          </button>
        </t-tooltip>
      </div>
      <div v-if="$slots.upload" class="doc-filter-actions"><slot name="upload" /></div>
    </div>
  </div>
</template>

<style scoped lang="less">
// Wrap by content as well as pane width: long paths must not squeeze out actions.
.doc-filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-shrink: 0;
  padding: 0 0 16px;
  border-bottom: 1px solid var(--td-component-stroke);
  &__trailing {
    display: flex;
    flex: 0 1 auto;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    min-width: 0;
    max-width: 100%;
    margin-left: auto;
    > :not(.doc-search-input) { flex-shrink: 0; }
  }
  .doc-search-input { width: 220px; min-width: 100px; }
  :deep(.doc-search-input .t-input) {
    background: transparent;
    border-color: var(--td-component-stroke);
    border-radius: var(--app-radius-md);
    font-size: var(--app-text-md);
  }
  .doc-filter-actions :deep(.content-bar-icon-btn) {
    height: 32px;
    padding: 0 12px;
    border-radius: var(--app-radius-md);
    background: var(--td-brand-color);
    color: var(--td-text-color-anti);
    &:hover { background: var(--td-brand-color-hover); }
  }
}
.doc-folder-path {
  display: flex;
  flex: 1 1 auto;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
  min-height: 32px;
  line-height: 20px;
  flex-wrap: wrap;
  &__tree-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    align-self: center;
    gap: 6px;
    height: 32px;
    padding: 0 10px;
    font: inherit;
    font-size: var(--app-text-md);
    border: 1px solid var(--td-component-stroke);
    border-radius: var(--app-radius-md);
    background: var(--td-bg-color-container);
    color: var(--td-text-color-secondary);
    cursor: pointer;
    &:hover { background: var(--td-bg-color-container-hover); color: var(--td-text-color-primary); }
  }
  &__crumb {
    max-width: 160px;
    padding: 6px 2px;
    border: 0;
    background: transparent;
    color: var(--td-text-color-secondary);
    font: inherit;
    font-size: var(--app-text-md);
    line-height: 20px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: pointer;
    &:is(button):hover { color: var(--td-brand-color); }
    &.is-current { color: var(--td-text-color-primary); font-weight: 600; cursor: default; }
  }
  &__count { padding: 6px 0; line-height: 20px; margin-left: 6px; color: var(--td-text-color-placeholder); font-size: var(--app-text-sm); font-variant-numeric: tabular-nums; white-space: nowrap; }
  &__sep, &__scope { align-self: center; flex-shrink: 0; color: var(--td-text-color-placeholder); font-size: var(--app-text-sm); }
}
.doc-view-toggle {
  display: inline-flex;
  align-items: center;
  background: var(--td-bg-color-secondarycontainer);
  border: 1px solid transparent;
  border-radius: var(--app-radius-md);
  padding: 2px;
  .doc-view-toggle-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 26px;
    padding: 0;
    border: 0;
    border-radius: var(--app-radius-xs);
    background: transparent;
    color: var(--td-text-color-placeholder);
    cursor: pointer;
    &:hover { color: var(--td-text-color-primary); }
    &.active { background: var(--td-bg-color-container); color: var(--td-brand-color); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08); }
  }
}
@container doc-card-area (max-width: 780px) {
  .doc-filter-bar { flex-wrap: wrap; gap: 12px; }
  .doc-filter-bar__trailing { width: 100%; }
  .doc-filter-bar .doc-search-input { flex: 1; width: auto; }
}

@container doc-card-area (max-width: 540px) {
  .doc-filter-bar__trailing { flex-wrap: wrap; }
  .doc-filter-bar .doc-search-input { flex: 1 0 100%; }
}


.doc-filter-bar button:focus-visible { outline: 2px solid var(--app-focus-border); outline-offset: 2px; }
</style>
