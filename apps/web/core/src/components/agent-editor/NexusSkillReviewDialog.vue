<template>
  <!-- A dialog around NexusSkillReviewPanel.vue; the panel is mounted only while the dialog is open, so it starts fresh each time. -->
  <t-dialog :visible="visible" :header="$t('nexusAgent.review.title')" width="760px" :footer="false"
    :z-index="2000" @close="emit('update:visible', false)">
    <NexusSkillReviewPanel v-if="visible" :tenant-id="tenantId" @changed="emit('changed')" />
  </t-dialog>
</template>

<script setup lang="ts">
import NexusSkillReviewPanel from './NexusSkillReviewPanel.vue'

defineProps<{ visible: boolean, tenantId: string }>()
const emit = defineEmits<{ (event: 'update:visible', value: boolean): void, (event: 'changed'): void }>()
</script>
