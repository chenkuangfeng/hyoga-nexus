<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useEnterpriseContext } from './stores/context'
import SettingsRow from '@nexus-web/core/components/SettingsRow.vue'
const { t } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
</script>
<template>
  <section class="admin-overview">
    <header class="section-header"><div><h2>{{ auth.currentTenantName }} · {{ t('adminConsole.overview') }}</h2><p class="section-description">{{ t('adminConsole.overviewHint') }}</p></div></header>
    <div class="settings-group">
      <SettingsRow v-if="context.can('policy:manage')" :label="t('adminConsole.policy')" :description="t('adminConsole.policyHint')"><RouterLink class="settings-entry" to="/policy">{{ t('adminConsole.openPolicy') }}<t-icon name="chevron-right" /></RouterLink></SettingsRow>
      <SettingsRow v-if="context.can('members:manage')" :label="t('adminMembers.title')" :description="t('adminMembers.description')"><RouterLink class="settings-entry" to="/members">{{ t('adminMembers.open') }}<t-icon name="chevron-right" /></RouterLink></SettingsRow>
      <SettingsRow v-if="context.can('org:manage')" :label="t('adminOrganization.title')" :description="t('adminOrganization.description')"><RouterLink class="settings-entry" to="/organization">{{ t('adminOrganization.open') }}<t-icon name="chevron-right" /></RouterLink></SettingsRow>
      <SettingsRow v-if="context.can('enterprise_agents:manage')" :label="t('adminAgents.title')" :description="t('adminAgents.description')"><RouterLink class="settings-entry" to="/agents">{{ t('adminAgents.open') }}<t-icon name="chevron-right" /></RouterLink></SettingsRow>
      <SettingsRow v-if="context.can('enterprise_kbs:manage')" :label="t('adminKnowledge.title')" :description="t('adminKnowledge.description')"><RouterLink class="settings-entry" to="/knowledge">{{ t('adminKnowledge.open') }}<t-icon name="chevron-right" /></RouterLink></SettingsRow>
    </div>
    <t-alert theme="info" :message="t('adminConsole.planned')" />
  </section>
</template>
<style scoped>
.admin-overview { width: 100%; }
.settings-group { margin-bottom: 28px; }
.settings-entry { display: inline-flex; align-items: center; gap: 8px; min-height: 32px; padding: 0 12px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); font-size: var(--app-text-md); }
a { color: var(--td-brand-color); text-decoration: none; }
a:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
</style>
