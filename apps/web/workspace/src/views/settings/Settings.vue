<script setup lang="ts">
/** 员工账户设置始终弹窗；仅挂载账户自身能力，旧治理书签只显示迁移说明。 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SettingsModalShell from '@nexus-web/core/components/SettingsModalShell.vue'
import { useModalShell } from '@nexus-web/core/composables/useModalShell'
import { useUIStore } from '@/stores/ui'
import GeneralSettings from './GeneralSettings.vue'
import UserProfile from './UserProfile.vue'
import NexusMemorySettings from './NexusMemorySettings.vue'
import AdminSectionMoved from './AdminSectionMoved.vue'
import { isMigratedAdminSection } from '@/config/settingsRoute'
const route = useRoute(), router = useRouter(), ui = useUIStore(), { t } = useI18n()
const allowed = ['general', 'userprofile', 'mymemory']
const visible = computed(() => route.path === '/platform/settings' || ui.showSettingsModal)
const section = computed(() => {
  const candidate = route.path === '/platform/settings' ? route.query.section : ui.settingsInitialSection
  return typeof candidate === 'string' && (allowed.includes(candidate) || isMigratedAdminSection(candidate)) ? candidate : 'general'
})
const groups = computed(() => [{ key: 'account', label: t('settings.navGroups.account'), items: [
  { key: 'general', label: t('general.title'), icon: 'setting' },
  { key: 'userprofile', label: t('userProfile.title'), icon: 'user' },
  { key: 'mymemory', label: t('memorySettings.title'), icon: 'bookmark' },
] }])
function select(value: string) {
  if (!allowed.includes(value)) return
  if (route.path === '/platform/settings') void router.replace({ path: route.path, query: { section: value } })
  else ui.openSettings(value)
}
function close() {
  ui.closeSettings()
  if (route.path === '/platform/settings') {
    const back = router.options.history.state.back
    if (typeof back === 'string' && back.startsWith('/platform/') && !back.startsWith('/platform/settings')) router.back()
    else void router.replace('/platform/creatChat')
  }
}
const shell = useModalShell({ visible: () => visible.value, close })

</script>
<template>
  <SettingsModalShell :visible="visible" :title="t('general.settings')" :model-value="section" :nav-groups="groups" @update:model-value="select" @close="shell.requestClose">
    <div class="section">
      <GeneralSettings v-if="section === 'general'" />
      <UserProfile v-else-if="section === 'userprofile'" />
      <NexusMemorySettings v-else-if="section === 'mymemory'" />
      <AdminSectionMoved v-else-if="isMigratedAdminSection(section)" :section="section" />
    </div>
  </SettingsModalShell>
</template>
