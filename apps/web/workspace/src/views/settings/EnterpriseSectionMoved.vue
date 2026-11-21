<script setup lang="ts">
/** 旧企业管理书签的迁移说明：只提供显式链接，不读取或修改企业治理配置。 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { enterpriseSettingsLocation, MIGRATED_ENTERPRISE_SECTIONS, type MigratedEnterpriseSection } from '@/config/settingsRoute'
const props = withDefaults(defineProps<{ section?: MigratedEnterpriseSection }>(), { section: 'org-structure' })
const destination = computed(() => MIGRATED_ENTERPRISE_SECTIONS[props.section])
const members = computed(() => props.section === 'members')
const auth = useAuthStore(), { t } = useI18n()
const canOpen = computed(() => auth.currentEntries.includes('enterprise'))
const href = computed(() => enterpriseSettingsLocation(import.meta.env.BASE_URL, destination.value.target))
const auditHref = enterpriseSettingsLocation(import.meta.env.BASE_URL, 'audit')
</script>
<template>
  <section class="enterprise-section-moved">
    <h2>{{ t(destination.titleKey) }}</h2>
    <p>{{ t(destination.messageKey) }}</p>
    <div v-if="canOpen" class="enterprise-links"><a class="enterprise-entry" :href="href">{{ t('adminMigration.openAdmin') }}<t-icon name="chevron-right" aria-hidden="true" /></a><a v-if="members" class="enterprise-entry" :href="auditHref">{{ t('adminAudit.title') }}</a></div>
    <t-alert v-else theme="info" :message="t('adminMigration.noEntry')" />
  </section>
</template>
<style scoped>
.enterprise-section-moved { max-width: 640px; }
h2 { font-size: var(--app-text-xl); margin: 0 0 16px; }
p { color: var(--td-text-color-secondary); line-height: 1.6; margin: 0 0 20px; }
.enterprise-links { display: flex; flex-wrap: wrap; gap: 12px; }
.enterprise-entry { display: inline-flex; align-items: center; gap: 8px; min-height: 36px; padding: 0 12px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); color: var(--td-brand-color); text-decoration: none; }
.enterprise-entry:hover { background: var(--td-bg-color-container-hover); }
.enterprise-entry:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
</style>
