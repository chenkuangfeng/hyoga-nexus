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
  <SettingsModalShell :visible="visible" overlay-class="all-settings-overlay workspace-account-settings" :title="t('general.settings')" :model-value="section" :nav-groups="groups" @update:model-value="select" @close="shell.requestClose">
    <div class="content-wrapper" :class="{ 'content-wrapper--resource-list': section === 'mymemory' }"><div class="section">
      <GeneralSettings v-if="section === 'general'" />
      <UserProfile v-else-if="section === 'userprofile'" />
      <NexusMemorySettings v-else-if="section === 'mymemory'" />
      <AdminSectionMoved v-else-if="isMigratedAdminSection(section)" :section="section" />
    </div></div>
  </SettingsModalShell>
</template>

<style lang="less">
/* 恢复 WeKnora Settings.vue 的设置专用尺寸，保持其他资源编辑器的壳尺寸独立。 */
.settings-modal-shell.workspace-account-settings > .settings-modal { max-width: 1280px; height: 900px; }
.workspace-account-settings .settings-body { padding: 0; }
</style>
<style scoped>
.content-wrapper { width: 100%; min-width: 0; box-sizing: border-box; padding: 40px 48px; }
.content-wrapper--resource-list { flex: 1; min-height: 0; padding: 20px 28px 0; }
.section { animation: workspace-account-enter .3s ease; }
@keyframes workspace-account-enter { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@media(max-width:720px) { .content-wrapper { padding: 24px; } .content-wrapper--resource-list { padding: 16px 16px 0; } }
@media(max-width:600px) { .content-wrapper { padding: 16px; } }
@media(prefers-reduced-motion:reduce) { .section { animation: none; } }
</style>
