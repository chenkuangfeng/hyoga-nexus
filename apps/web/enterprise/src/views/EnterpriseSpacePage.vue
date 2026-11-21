<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import EnterpriseInfo from './EnterpriseInfo.vue'
import SpaceMemorySettings from './memory/SpaceMemorySettings.vue'
const tab = ref(useAuthStore().currentTenantRole === 'owner' ? 'info' : 'memory'), { t } = useI18n(), auth = useAuthStore()
</script>
<template><t-tabs v-model="tab"><t-tab-panel v-if="auth.currentTenantRole === 'owner'" value="info" :label="t('consoleLayout.space')"><EnterpriseInfo v-if="tab === 'info'" /></t-tab-panel><t-tab-panel value="memory" :label="t('consoleLayout.memory')"><SpaceMemorySettings v-if="tab === 'memory'" /></t-tab-panel></t-tabs></template>
