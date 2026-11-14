<script setup lang="ts">
/** 旧部门设置书签的迁移说明，不读取或修改企业组织数据。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { adminOrganizationLocation } from '@/config/settingsRoute'
const auth = useAuthStore(), { t } = useI18n()
const canOpen = computed(() => auth.currentEntries.includes('admin'))
const href = adminOrganizationLocation(import.meta.env.BASE_URL, window.location.origin, import.meta.env.DEV)
</script>
<template>
  <section class="admin-section-moved">
    <h2>{{ t('adminOrganization.title') }}</h2>
    <p>{{ t('adminMigration.organizationMoved') }}</p>
    <a v-if="canOpen" class="admin-entry" :href="href">{{ t('adminMigration.openAdmin') }}<t-icon name="chevron-right" aria-hidden="true" /></a>
    <t-alert v-else theme="info" :message="t('adminMigration.noEntry')" />
  </section>
</template>
<style scoped>
.admin-section-moved { max-width: 640px; }
h2 { font-size: var(--app-text-xl); margin: 0 0 16px; }
p { color: var(--td-text-color-secondary); line-height: 1.6; margin: 0 0 20px; }
.admin-entry { display: inline-flex; align-items: center; gap: 8px; min-height: 36px; padding: 0 12px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); color: var(--td-brand-color); text-decoration: none; }
.admin-entry:hover { background: var(--td-bg-color-container-hover); }
.admin-entry:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
</style>
