<template>
  <!--
    Nexus toolbox (openspec 2026-11-08-toolbox). Layout and styles follow WeKnora's Toolbox.vue; the panels are Nexus's own
    and call the Nexus API. Tabs whose backend does not exist yet stay in the bar, disabled and marked "planned", and never
    send a request.
  -->
  <main class="toolbox-page">
    <header class="toolbox-header">
      <div class="toolbox-title-row">
        <h2>
          <ResourceIcon type="toolbox" :size="24" />
          {{ t('toolbox.title') }}
        </h2>
      </div>
      <p class="toolbox-subtitle">{{ t(selectedItem?.description ?? 'toolbox.description') }}</p>
    </header>

    <EmptyState v-if="!tenantId" icon="usergroup" :title="t('nexusAgent.noSpace')" />
    <template v-else-if="visibleItems.length">
      <div class="toolbox-tabbar">
        <div class="toolbox-tabs" role="tablist" :aria-label="t('toolbox.title')">
          <button v-for="item in visibleItems" :key="item.key" type="button" role="tab" class="toolbox-tab"
            :aria-selected="selectedItem?.key === item.key" :aria-disabled="!item.available" :disabled="!item.available"
            @click="select(item.key)">
            <t-icon :name="item.icon" size="16px" />
            <span>{{ t(item.title) }}</span>
            <span v-if="!item.available" class="toolbox-tab-count">{{ t('toolbox.planned') }}</span>
            <span v-else-if="counts[item.key] !== undefined" class="toolbox-tab-count">{{ counts[item.key] }}</span>
          </button>
        </div>
      </div>

      <section v-if="selectedItem" class="toolbox-main" role="tabpanel">
        <div class="toolbox-panel">
          <NexusToolboxSkills v-if="selectedItem.key === 'skills'" :tenant-id="tenantId" @count="counts.skills = $event" />
          <NexusToolboxTools v-else-if="selectedItem.key === 'tools'" :tenant-id="tenantId" @count="counts.tools = $event" />
          <NexusToolboxMcp v-else-if="selectedItem.key === 'mcp'" :tenant-id="tenantId" @count="counts.mcp = $event" />
        </div>
      </section>
    </template>

    <EmptyState v-else icon="tools" :title="t('toolbox.unavailable')" />
  </main>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import {
  TOOLBOX_ITEMS,
  canAccessToolboxSection,
  isToolboxSectionAvailable,
  toolboxLocation,
  type ToolboxSection,
} from '@/config/toolbox'
import ResourceIcon from '@/components/icons/ResourceIcon.vue'
import EmptyState from '@/components/EmptyState.vue'
import NexusToolboxMcp from './NexusToolboxMcp.vue'
import NexusToolboxSkills from './NexusToolboxSkills.vue'
import NexusToolboxTools from './NexusToolboxTools.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const counts = reactive<Partial<Record<ToolboxSection, number>>>({})
const tenantId = computed(() => authStore.effectiveTenantId ? String(authStore.effectiveTenantId) : '')
const requestedSection = computed(() => typeof route.params.section === 'string' ? route.params.section : '')
const visibleItems = computed(() => TOOLBOX_ITEMS.filter((item) => canAccessToolboxSection(item.key, {
  currentTenantRole: authStore.currentTenantRole,
  canAccessAllTenants: authStore.canAccessAllTenants,
})))
// Only an available tab can be open: a planned one is shown but never selected.
const selectedItem = computed(() => visibleItems.value.find((item) => item.key === requestedSection.value && item.available))

const select = (section: ToolboxSection) => {
  if (!isToolboxSectionAvailable(section) || section === requestedSection.value) return
  void router.replace(toolboxLocation(section))
}

// The bare /toolbox URL, a planned tab typed into the address bar, and tabs lost to a workspace switch land on the
// first tab that can be opened.
watch([selectedItem, visibleItems], () => {
  const fallback = visibleItems.value.find((item) => item.available)
  if (!selectedItem.value && fallback) void router.replace(toolboxLocation(fallback.key))
}, { immediate: true })
</script>

<style scoped lang="less">
@import (reference) '@/components/css/resource-card.less';

.toolbox-page {
  .resource-list-content();
  color: var(--td-text-color-primary);
}

.toolbox-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
  flex-shrink: 0;

  h2 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    font-family: var(--app-font-family);
    font-size: var(--app-text-4xl);
    font-weight: 600;
    line-height: 32px;
  }
}

.toolbox-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-4);
}

.toolbox-action.t-button {
  flex-shrink: 0;
  min-height: 32px;
  padding: 0 12px;
  gap: 6px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-sm);
  background: var(--td-bg-color-container);
  color: var(--td-text-color-primary);
  font-size: var(--app-text-md);
  transition: background var(--app-motion-base);

  &:hover:not(:disabled) {
    border-color: var(--td-component-stroke);
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

.toolbox-subtitle {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-base);
  line-height: 20px;
}

.toolbox-help {
  flex-shrink: 0;
  color: var(--td-text-color-placeholder);
  font-size: var(--app-text-md);
  cursor: help;

  &:hover {
    color: var(--td-text-color-secondary);
  }
}

.toolbox-tabbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
  border-bottom: 1px solid var(--td-component-stroke);
}

.toolbox-tabs {
  flex: 1;
  min-width: 0;
  display: flex;
  gap: 24px;
  overflow-x: auto;
  scrollbar-width: none;
}

.toolbox-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;

  :deep(.t-input__wrap) {
    width: 240px;
  }

  :deep(.t-input) {
    border-radius: var(--app-radius-sm);
  }
}

.toolbox-tab {
  position: relative;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 44px;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: var(--td-text-color-secondary);
  font: inherit;
  font-size: var(--app-text-base);
  font-weight: 500;
  cursor: pointer;
  transition: color var(--app-motion-fast) ease;

  &::after {
    content: '';
    position: absolute;
    left: 0;
    right: 0;
    bottom: -1px;
    height: 2px;
    border-radius: var(--app-radius-pill);
    background: transparent;
    transition: background var(--app-motion-fast) ease;
  }

  &:hover {
    color: var(--td-text-color-primary);
  }

  &[aria-selected='true'] {
    color: var(--td-text-color-primary);

    > .t-icon, > svg {
      color: var(--td-brand-color);
    }

    &::after {
      background: var(--td-brand-color);
    }

    .toolbox-tab-count {
      background: var(--td-brand-color-light);
      color: var(--td-brand-color);
    }
  }

  &:focus-visible {
    outline: 2px solid var(--td-brand-color);
    outline-offset: -2px;
    border-radius: var(--app-radius-sm);
  }
}

.toolbox-tab-count {
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

.toolbox-tab-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--td-text-color-placeholder);
  font-size: var(--app-text-xs);
  font-weight: 400;

  i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
  }

  &.is-connected {
    color: var(--td-success-color);
  }

  &.is-offline {
    color: var(--td-warning-color);
  }
}

.toolbox-main {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--app-space-4) 0 var(--app-space-8);
}

.toolbox-panel {
  // Panels are shared with the settings dialog; here the tab and page header
  // already carry their title and description.
  > :deep(* > .section-header) {
    display: none;
  }
}

@media (max-width: 768px) {
  .toolbox-tabbar {
    flex-wrap: wrap;
  }

  .toolbox-tabs {
    flex-basis: 100%;
    gap: 20px;
  }

  .toolbox-toolbar {
    width: 100%;
    padding: 8px 0;

    &:empty {
      display: none;
    }

    :deep(.t-input__wrap) {
      width: 100%;
    }
  }
}
</style>

<style scoped lang="less">
.toolbox-tab:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
</style>
