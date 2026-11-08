<template>
  <!-- A dialog around NexusSkillInstallPanel.vue; the panel is mounted only while the dialog is open, so it starts fresh each time. -->
  <t-dialog :visible="visible" :header="$t('nexusAgent.skillInstall.title')" width="640px" :footer="false" :close-on-overlay-click="false"
    :z-index="2000" @close="emit('update:visible', false)">
    <NexusSkillInstallPanel v-if="visible" :tenant-id="tenantId" :sandbox-profile="sandboxProfile" @installed="emit('installed')" />
  </t-dialog>
</template>

<script setup lang="ts">
import NexusSkillInstallPanel from './NexusSkillInstallPanel.vue'

defineProps<{ visible: boolean, tenantId: string, sandboxProfile?: string }>()
const emit = defineEmits<{ (event: 'update:visible', value: boolean): void, (event: 'installed'): void }>()
</script>
