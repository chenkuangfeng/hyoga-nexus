<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from './stores/context'
const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
</script>
<template>
  <section class="admin-overview">
    <h1>{{ auth.currentTenantName }} · {{ t('adminConsole.overview') }}</h1>
    <p>{{ t('adminConsole.overviewHint') }}</p>
    <article v-if="context.can('policy:manage')"><h2>{{ t('adminConsole.policy') }}</h2><p>{{ t('adminConsole.policyHint') }}</p><RouterLink to="/policy">{{ t('adminConsole.openPolicy') }}</RouterLink></article>
    <article v-if="context.can('members:manage')"><h2>{{ t('adminMembers.title') }}</h2><p>{{ t('adminMembers.description') }}</p><RouterLink to="/members">{{ t('adminMembers.open') }}</RouterLink></article>
    <article v-if="context.can('org:manage')"><h2>{{ t('adminOrganization.title') }}</h2><p>{{ t('adminOrganization.description') }}</p><RouterLink to="/organization">{{ t('adminOrganization.open') }}</RouterLink></article>
    <t-alert theme="info" :message="t('adminConsole.planned')" />
  </section>
</template>
<style scoped>
.admin-overview { max-width: 1000px; }
h1 { margin-top: 0; font-size: 24px; } p { color: var(--td-text-color-secondary); line-height: 1.6; }
article { background: var(--td-bg-color-container); border: 1px solid var(--td-component-border); border-radius: var(--td-radius-default); padding: 24px; margin: 24px 0; }
a { color: var(--td-brand-color); }
</style>
