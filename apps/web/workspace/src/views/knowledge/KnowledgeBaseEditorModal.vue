<script setup lang="ts">
/** 工作台组合入口：完整表单在 core，导航与工作台弹层状态留在应用中。 */
import SharedKnowledgeBaseEditorModal from '@nexus-web/core/components/knowledge-editor/KnowledgeBaseEditorModal.vue'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useUIStore } from '@/stores/ui'
const props = defineProps<{visible:boolean;mode:'create'|'edit';kbId?:string;initialType?:'document'|'faq'|'wiki'}>()
const emit = defineEmits<{(event:'update:visible',value:boolean):void;(event:'success',id:string):void}>()
const auth = useAuthStore(), ui = useUIStore()
function openSettings(section:string, tab?:string) { ui.openSettings(section, tab) }
</script>
<template>
  <SharedKnowledgeBaseEditorModal v-if="mode === 'edit'" v-bind="props" :key="String(auth.effectiveTenantId) + ':' + auth.user?.id" :tenant-id="String(auth.effectiveTenantId || '')" :initial-section="ui.kbEditorInitialSection ?? undefined" :settings-visible="ui.showSettingsModal" @open-settings="openSettings" @update:visible="emit('update:visible', $event)" @success="emit('success', $event)" />
</template>
