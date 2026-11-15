<script setup lang="ts">
/** 工作台保留工具箱宿主；MCP 管理实现由 core 提供给两应用复用。 */
import NexusToolboxMcpCore from '@nexus-web/core/components/mcp-admin/NexusToolboxMcp.vue'
const props = defineProps<{ tenantId: string }>()
const emit = defineEmits<{ (event: 'count', value: number): void }>()
</script>
<template><NexusToolboxMcpCore :tenant-id="props.tenantId" @count="emit('count', $event)" /></template>
