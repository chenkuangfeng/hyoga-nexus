<script setup lang="ts">
/** 旧企业管理书签的迁移说明：只提供显式链接，不读取或修改企业治理配置。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { adminSettingsLocation, MIGRATED_ADMIN_SECTIONS, type MigratedAdminSection } from '@/config/settingsRoute'
const props = withDefaults(defineProps<{ section?: MigratedAdminSection }>(), { section: 'org-structure' })
const destination = computed(() => MIGRATED_ADMIN_SECTIONS[props.section])
const members = computed(() => props.section === 'members')
const auth = useAuthStore(), { t } = useI18n()
const canOpen = computed(() => auth.currentEntries.includes('admin'))
const href = computed(() => adminSettingsLocation(import.meta.env.BASE_URL, window.location.origin, import.meta.env.DEV, destination.value.target))
const auditHref = adminSettingsLocation(import.meta.env.BASE_URL, window.location.origin, import.meta.env.DEV, 'audit')
</script>
<template>
  <section class="admin-section-moved">
    <h2>{{ t(destination.titleKey) }}</h2>
    <p>{{ t(destination.messageKey) }}</p>
    <div v-if="canOpen" class="admin-links"><a class="admin-entry" :href="href">{{ t('adminMigration.openAdmin') }}<t-icon name="chevron-right" aria-hidden="true" /></a><a v-if="members" class="admin-entry" :href="auditHref">{{ t('adminAudit.title') }}</a></div>
    <t-alert v-else theme="info" :message="t('adminMigration.noEntry')" />
  </section>
</template>
<style scoped>
.admin-section-moved { max-width: 640px; }
h2 { font-size: var(--app-text-xl); margin: 0 0 16px; }
p { color: var(--td-text-color-secondary); line-height: 1.6; margin: 0 0 20px; }
.admin-links { display: flex; flex-wrap: wrap; gap: 12px; }
.admin-entry { display: inline-flex; align-items: center; gap: 8px; min-height: 36px; padding: 0 12px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); color: var(--td-brand-color); text-decoration: none; }
.admin-entry:hover { background: var(--td-bg-color-container-hover); }
.admin-entry:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
</style>
