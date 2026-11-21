<script setup lang="ts">
/** WeKnora Toolbox.vue 标题与标签栏，保留 Nexus 工具、技能及 MCP 页面地址。 */
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n()
const route = useRoute()
const context = useEnterpriseContext()
const items = [
  { path: '/skills', icon: 'check-circle', label: 'consoleLayout.skills', description: 'settings.skills.description', panel: defineAsyncComponent(() => import('../skills/SkillsPage.vue')) },
  { path: '/mcp-services', icon: 'tools', label: 'consoleLayout.mcpRegister', description: 'mcpSettings.description', panel: defineAsyncComponent(() => import('../connections/McpServicesPage.vue')) },
  { path: '/tools', icon: 'assignment', label: 'consoleLayout.tools', description: 'adminToolCatalog.description', panel: defineAsyncComponent(() => import('./ToolCatalogPage.vue')) },
]
const selected = computed(() => items.find(item => item.path === route.path))
const count = ref<number>()
watch(() => [route.path, context.revision], () => { count.value = undefined }, { flush: 'sync' })
</script>

<template>
  <section class="toolbox-page">
    <header class="toolbox-header">
      <div class="toolbox-title-row">
        <h2><t-icon name="tools" size="24px" aria-hidden="true" />{{ t('consoleLayout.toolbox') }}</h2>
        <div id="enterprise-toolbox-action" />
      </div>
      <p v-if="selected" class="toolbox-subtitle">{{ t(selected.description) }}</p>
    </header>
    <t-alert v-if="!context.can('tools:manage')" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <div class="toolbox-tabbar">
        <nav class="toolbox-tabs" :aria-label="t('consoleLayout.toolbox')">
          <RouterLink v-for="item in items" :key="item.path" :to="item.path" class="toolbox-tab"
            :aria-current="selected?.path === item.path ? 'page' : undefined">
            <t-icon :name="item.icon" size="16px" aria-hidden="true" /><span>{{ t(item.label) }}</span>
            <span v-if="selected?.path === item.path && count !== undefined" class="toolbox-tab-count">{{ count }}</span>
          </RouterLink>
        </nav>
        <div id="enterprise-toolbox-search" class="toolbox-toolbar" />
      </div>
      <section v-if="selected" class="toolbox-main">
        <div class="toolbox-panel"><component :is="selected.panel" :key="selected.path" embedded @count="count = $event" /></div>
      </section>
    </template>
  </section>
</template>

<style scoped lang="less">
@import './ToolboxPage.reference.less';
</style>
