<script setup lang="ts">
/** 兼容工作台工具箱的既有导入路径。 */
import NexusMcpKeyValueEditorCore from '@nexus-web/core/components/mcp-admin/NexusMcpKeyValueEditor.vue'
import type { McpKeyValueRow } from '@nexus-web/core/components/mcp-admin/toolboxMcp'
defineProps<{ modelValue: McpKeyValueRow[] }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: McpKeyValueRow[]): void }>()
</script>
<template><NexusMcpKeyValueEditorCore :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)" /></template>
