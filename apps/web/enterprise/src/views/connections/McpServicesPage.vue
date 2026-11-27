<script setup lang="ts">
/** 管理端组合企业 MCP 客户端目录；管理权限由企业权限上下文控制。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import NexusToolboxMcp from '@nexus-web/core/components/mcp-admin/NexusToolboxMcp.vue'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const scopeKey = computed(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}`)
const props = defineProps<{ embedded?: boolean }>()
const emit = defineEmits<{ count: [value: number] }>()
</script>

<template>
  <section class="mcp-services-page">
    <header v-if="!props.embedded" class="section-header"><h2>{{ t('consoleLayout.mcpRegister') }}</h2></header>
    <t-alert v-if="!context.can('tools:manage')" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <NexusToolboxMcp :key="scopeKey" :tenant-id="tenant" :can-manage="true" :show-intro="false"
        :action-target="props.embedded ? '#enterprise-toolbox-action' : undefined"
        :search-target="props.embedded ? '#enterprise-toolbox-search' : undefined" @count="emit('count', $event)" />
    </template>
  </section>
</template>

<style scoped>
.mcp-services-page { min-width: 0; }
</style>
