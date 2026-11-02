<script setup lang="ts">
/**
 * Workbench frame: sidebar on the left, routed page on the right.
 *
 * Widths: ≥1024px sidebar expanded (unless the user collapsed it), 768–1023px icon column,
 * <768px the sidebar is a drawer opened from the top bar. The collapsed choice is remembered.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AppSidebar from './AppSidebar.vue'
import SettingsDialog from './SettingsDialog.vue'
import { workspace } from '../stores/workspace'

const emit = defineEmits<{ signOut: [] }>()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const settingsOpen = ref(false)
// Route titles are i18n keys (`meta.titleKey`); the page title follows the interface language.
const pageTitle = computed(() => (route.meta.titleKey ? t(String(route.meta.titleKey)) : t('shell.pages.chat')))
const STORAGE_KEY = 'nexus_sidebar_collapsed'
const narrow = window.matchMedia('(max-width: 767px)')
const medium = window.matchMedia('(max-width: 1023px)')
const isNarrow = ref(narrow.matches), isMedium = ref(medium.matches)
const stored = localStorage.getItem(STORAGE_KEY)
const preference = ref<boolean | null>(stored === null ? null : stored === 'true')
const drawerOpen = ref(false)
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

// Without a stored choice, the sidebar is an icon column on medium screens.
const collapsed = computed(() => (isNarrow.value ? false : preference.value ?? isMedium.value))
const sidebarHidden = computed(() => isNarrow.value && !drawerOpen.value)

function toggle() {
  if (isNarrow.value) { drawerOpen.value = !drawerOpen.value; return }
  preference.value = !collapsed.value
  localStorage.setItem(STORAGE_KEY, String(preference.value))
}
function onNavigate() { if (isNarrow.value) drawerOpen.value = false }
function onMediaChange() { isNarrow.value = narrow.matches; isMedium.value = medium.matches; if (!narrow.matches) drawerOpen.value = false }
function onKey(event: KeyboardEvent) { if (event.key === 'Escape' && drawerOpen.value) drawerOpen.value = false }

onMounted(() => {
  narrow.addEventListener('change', onMediaChange); medium.addEventListener('change', onMediaChange)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  narrow.removeEventListener('change', onMediaChange); medium.removeEventListener('change', onMediaChange)
  window.removeEventListener('keydown', onKey)
})

// Admin pages are visible only to platform administrators; others go back to the conversation page.
const allowed = computed(() => !route.meta.requiresAdmin || !!workspace.user?.is_platform_admin)
watch(() => [route.fullPath, workspace.user?.is_platform_admin], () => {
  if (route.path === '/login' || !allowed.value) void router.replace('/chat')
}, { immediate: true })
</script>

<template>
  <div class="app-frame" :class="{ 'app-frame--narrow': isNarrow, 'app-frame--motion-reduced': reduceMotion.matches }">
    <header v-if="isNarrow" class="top-bar">
      <button type="button" class="icon-button" :aria-label="t('shell.openNav')" :aria-expanded="drawerOpen" aria-controls="app-sidebar" @click="toggle">☰</button>
      <strong>{{ pageTitle }}</strong>
    </header>
    <div v-if="isNarrow && drawerOpen" class="drawer-backdrop" aria-hidden="true" @click="drawerOpen = false" />
    <div id="app-sidebar" class="sidebar-slot" :class="{ 'sidebar-slot--drawer': isNarrow, 'sidebar-slot--open': drawerOpen }" :hidden="sidebarHidden || undefined">
      <AppSidebar :collapsed="collapsed" @toggle="toggle" @navigate="onNavigate" @sign-out="emit('signOut')" @open-settings="settingsOpen = true" />
    </div>
    <main class="page-slot" :aria-label="pageTitle">
      <router-view v-if="allowed" />
    </main>
    <SettingsDialog v-model="settingsOpen" />
  </div>
</template>

<style scoped>
.app-frame { display: grid; grid-template-columns: auto minmax(0, 1fr); min-height: 100vh; }
.app-frame--narrow { display: block; }
.sidebar-slot { position: sticky; top: 0; height: 100vh; }
.sidebar-slot--drawer { position: fixed; inset: 0 auto 0 0; z-index: 30; box-shadow: var(--shadow-3); }
.sidebar-slot--drawer:not(.sidebar-slot--open) { display: none; }
.drawer-backdrop { position: fixed; inset: 0; z-index: 20; background: var(--color-mask); }
.top-bar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: var(--surface); border-bottom: 1px solid var(--border); }
.icon-button { min-width: 44px; min-height: 44px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); cursor: pointer; font-size: 18px; }
.icon-button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.page-slot { min-width: 0; padding: 24px; box-sizing: border-box; }
.app-frame--narrow .page-slot { padding: 16px; }
@media (prefers-reduced-motion: reduce) { .app-sidebar { transition: none; } }
</style>
