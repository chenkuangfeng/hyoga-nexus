<script setup lang="ts">
/** 兼容工作台工具箱的既有导入路径。 */
import NexusMcpServiceDialogCore from '@nexus-web/core/components/mcp-admin/NexusMcpServiceDialog.vue'
import type { McpService } from '@nexus-web/core/api/nexus-mcp'
defineProps<{ visible: boolean; tenantId: string; service: McpService | null }>()
const emit = defineEmits<{ (event: 'update:visible', value: boolean): void; (event: 'saved', value: McpService): void }>()
</script>
<template><NexusMcpServiceDialogCore :visible="visible" :tenant-id="tenantId" :service="service" @update:visible="emit('update:visible', $event)" @saved="emit('saved', $event)" /></template>
