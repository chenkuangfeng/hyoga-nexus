<template>
  <!--
    平台管理（系统管理员专用）。独立整页替换主界面：不挂载侧栏、全局设置等 platform 布局，
    顶部「返回」回到知识库列表。内容复用 settings 体系中已有的系统管理组件，
    分区与 SYSTEM_ADMIN_SETTINGS_SECTIONS 保持一致；路由 meta.requiresSystemAdmin 负责前端门禁，
    真正的权限检查在后端 RequireSystemAdmin 中间件。
  -->
  <div class="platform-admin">
    <header class="platform-admin__header">
      <button type="button" class="platform-admin__back" @click="goBack">
        <t-icon name="chevron-left" />
        <span>{{ t('general.backToMain') }}</span>
      </button>
      <h1 class="platform-admin__title">{{ t('general.platformAdmin') }}</h1>
    </header>

    <div class="platform-admin__body">
      <nav class="platform-admin__nav" :aria-label="t('general.platformAdmin')">
        <button v-for="item in sections" :key="item.key" type="button" class="platform-admin__nav-item"
          :class="{ 'is-active': item.key === currentSection }"
          :aria-current="item.key === currentSection ? 'page' : undefined" @click="selectSection(item.key)">
          <t-icon :name="item.icon" class="platform-admin__nav-icon" />
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <main class="platform-admin__content">
        <SystemSettings v-if="currentSection === 'system-global'" />
        <ModelCatalog v-else-if="currentSection === 'model-catalog'" />
        <RuntimeQueues v-else-if="currentSection === 'runtime-queues'" />
        <PlatformAPIKeys v-else-if="currentSection === 'platform-api-keys'" />
        <SystemAuditLog v-else-if="currentSection === 'system-audit-log'" />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import SystemSettings from '@/views/system/SystemSettings.vue'
import ModelCatalog from '@/views/system/ModelCatalog.vue'
import RuntimeQueues from '@/views/system/RuntimeQueues.vue'
import PlatformAPIKeys from '@/views/system/PlatformAPIKeys.vue'
import SystemAuditLog from '@/views/system/SystemAuditLog.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

type AdminSection = 'system-global' | 'model-catalog' | 'runtime-queues' | 'platform-api-keys' | 'system-audit-log'

// 分区顺序与设置页「系统管理」分组一致。
const sections = computed<{ key: AdminSection; icon: string; label: string }[]>(() => [
  { key: 'system-global', icon: 'server', label: t('settings.system') },
  { key: 'model-catalog', icon: 'control-platform', label: t('modelCatalog.title') },
  { key: 'runtime-queues', icon: 'queue', label: t('settings.taskQueue') },
  { key: 'platform-api-keys', icon: 'secured', label: t('platformApiKeys.title') },
  { key: 'system-audit-log', icon: 'history', label: t('system.globalSettings.audit.tabLabel') },
])

// 当前分区放在 query.section 中，刷新或分享链接时保持在同一分区；未知值回落到第一项。
const currentSection = computed<AdminSection>(() => {
  const raw = typeof route.query.section === 'string' ? route.query.section : ''
  return sections.value.find((item) => item.key === raw)?.key ?? 'system-global'
})

const selectSection = (key: AdminSection) => {
  if (key === currentSection.value) return
  router.replace({ path: route.path, query: { section: key } })
}

// 返回主界面：固定回到知识库列表，不依赖浏览历史（直接打开平台管理链接时历史为空）。
const goBack = () => {
  router.push('/platform/knowledge-bases')
}
</script>

<style lang="less" scoped>
.platform-admin {
  display: flex;
  flex-direction: column;
  width: 100vw;
  height: 100vh;
  min-height: 0;
  background: var(--td-bg-color-page);
  color: var(--td-text-color-primary);
  overflow: hidden;
}

.platform-admin__header {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
  height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid var(--td-component-stroke);
  background: var(--td-bg-color-container);
}

.platform-admin__back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 10px 0 6px;
  border: none;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--td-text-color-secondary);
  font: inherit;
  font-size: var(--app-text-md);
  cursor: pointer;
  transition: background var(--app-motion-fast) ease, color var(--app-motion-fast) ease;

  &:hover {
    background: var(--td-bg-color-container-hover);
    color: var(--td-text-color-primary);
  }

  &:focus-visible {
    outline: none;
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--td-brand-color) 25%, transparent);
  }
}

.platform-admin__title {
  margin: 0;
  font-size: var(--app-text-lg);
  font-weight: 600;
  line-height: 1.4;
}

.platform-admin__body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.platform-admin__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex-shrink: 0;
  width: 200px;
  padding: 16px 12px;
  border-right: 1px solid var(--td-component-stroke);
  background: var(--td-bg-color-container);
  overflow-y: auto;
}

.platform-admin__nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: none;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--td-text-color-secondary);
  font: inherit;
  font-size: var(--app-text-md);
  text-align: left;
  cursor: pointer;
  transition: background var(--app-motion-fast) ease, color var(--app-motion-fast) ease;

  &:hover {
    background: var(--td-bg-color-container-hover);
    color: var(--td-text-color-primary);
  }

  &:focus-visible {
    outline: none;
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--td-brand-color) 25%, transparent);
  }

  &.is-active {
    background: color-mix(in srgb, var(--td-brand-color) 10%, transparent);
    color: var(--td-brand-color);
    font-weight: 600;
  }
}

.platform-admin__nav-icon {
  flex-shrink: 0;
}

.platform-admin__content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 24px 32px;
  overflow-y: auto;
  box-sizing: border-box;
}

@media (max-width: 720px) {
  .platform-admin__body {
    flex-direction: column;
  }

  .platform-admin__nav {
    flex-direction: row;
    width: auto;
    padding: 8px 12px;
    border-right: none;
    border-bottom: 1px solid var(--td-component-stroke);
    overflow-x: auto;
    overflow-y: hidden;
  }

  .platform-admin__nav-item {
    width: auto;
    flex-shrink: 0;
  }

  .platform-admin__content {
    padding: 16px;
  }
}
</style>
