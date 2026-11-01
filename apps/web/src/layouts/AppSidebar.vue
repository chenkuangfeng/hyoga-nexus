<script setup lang="ts">
/**
 * Left sidebar, modelled on WeKnora's menu: a top row (search, collapse), the primary actions
 * (new chat with recent sessions, knowledge base, agents, shared space), the sessions grouped by
 * last update, the management groups, and the user menu (language, settings, sign-out).
 *
 * Width is user-adjustable by dragging the right edge or with the arrow keys on the separator; the
 * width is remembered. Collapsed mode shows only the icon column.
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { navigation } from '../router/navigation'
import { setLocale, LOCALES, type Locale } from '../i18n'
import { setTenant, workspace } from '../stores/workspace'
import type { Conversation } from '../types/chat'
import SessionSearch from './SessionSearch.vue'

const props = defineProps<{ collapsed: boolean }>()
const emit = defineEmits<{ toggle: []; navigate: []; signOut: []; openSettings: [] }>()
const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

const WIDTH_KEY = 'nexus_sidebar_width'
const MIN_WIDTH = 200, MAX_WIDTH = 360, DEFAULT_WIDTH = 248
const stored = Number(localStorage.getItem(WIDTH_KEY))
const width = ref(Number.isFinite(stored) && stored >= MIN_WIDTH && stored <= MAX_WIDTH ? stored : DEFAULT_WIDTH)
const searchOpen = ref(false)

const visibleGroups = computed(() => navigation.filter(group => !group.requiresAdmin || workspace.user?.is_platform_admin))
const activeSession = computed(() => (route.name === 'chat' ? String(route.params.sessionId || '') : ''))

function go(path: string) {
  void router.push(path)
  emit('navigate')
}
function openSession(id: string) { void router.push(`/chat/${id}`); emit('navigate') }
function isActive(path: string) { return route.path === path || route.path.startsWith(path + '/') }
/** 新对话: the conversation page starts a blank draft; the session is created on the first message. */
function newChat() {
  workspace.newChatTick++
  void router.push('/chat')
  emit('navigate')
}

/** Sessions grouped by last update: today, the last 30 days, and earlier. Newest first inside each group. */
const groups = computed(() => {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const monthAgo = startOfToday - 30 * 24 * 3600 * 1000
  const buckets = { today: [] as Conversation[], recent: [] as Conversation[], older: [] as Conversation[] }
  const sorted = [...workspace.sessions].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  for (const session of sorted) {
    const time = Date.parse(session.updated_at)
    if (time >= startOfToday) buckets.today.push(session)
    else if (time >= monthAgo) buckets.recent.push(session)
    else buckets.older.push(session)
  }
  return [
    { key: 'today', label: t('shell.groupToday'), items: buckets.today },
    { key: 'recent', label: t('shell.groupRecent'), items: buckets.recent },
    { key: 'older', label: t('shell.groupOlder'), items: buckets.older },
  ].filter(group => group.items.length)
})

// Resizing: pointer drag on the separator, or arrow keys for keyboard users.
let dragStartX = 0, dragStartWidth = 0, dragging = false
function clamp(value: number) { return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value)) }
function persistWidth() { localStorage.setItem(WIDTH_KEY, String(width.value)) }
function onDragStart(event: PointerEvent) {
  dragging = true; dragStartX = event.clientX; dragStartWidth = width.value
  window.addEventListener('pointermove', onDragMove); window.addEventListener('pointerup', onDragEnd)
}
function onDragMove(event: PointerEvent) { if (dragging) width.value = clamp(dragStartWidth + event.clientX - dragStartX) }
function onDragEnd() {
  if (!dragging) return
  dragging = false; persistWidth()
  window.removeEventListener('pointermove', onDragMove); window.removeEventListener('pointerup', onDragEnd)
}
function onSeparatorKey(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  width.value = clamp(width.value + (event.key === 'ArrowRight' ? 16 : -16))
  persistWidth()
}
onBeforeUnmount(() => { window.removeEventListener('pointermove', onDragMove); window.removeEventListener('pointerup', onDragEnd) })

const sidebarStyle = computed(() => (props.collapsed ? undefined : { width: `${width.value}px` }))

/** Language choice from the user menu. The choice is stored and applies immediately. */
function chooseLocale(value: Locale) { setLocale(value); locale.value = value }
function onUserCommand(command: string | number | object) {
  if (command === 'settings') emit('openSettings')
  else if (command === 'signOut') emit('signOut')
  else if (command === 'zh-CN' || command === 'en-US') chooseLocale(command)
}
</script>

<template>
  <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': collapsed }" :style="sidebarStyle" :aria-label="t('shell.space')">
    <div class="sidebar-head">
      <span class="brand" aria-hidden="true">HN</span>
      <span v-if="!collapsed" class="brand-name">Hyoga Nexus</span>
      <button v-if="!collapsed" type="button" class="icon-button" :aria-label="t('shell.search')" :title="t('shell.search')" @click="searchOpen = true">
        <span aria-hidden="true">⌕</span>
      </button>
      <button type="button" class="icon-button" :aria-label="collapsed ? t('shell.expandNav') : t('shell.collapseNav')" :aria-expanded="!collapsed" @click="emit('toggle')">
        <span aria-hidden="true">{{ collapsed ? '›' : '‹' }}</span>
      </button>
    </div>
    <button v-if="collapsed" type="button" class="icon-button icon-button--solo" :aria-label="t('shell.search')" :title="t('shell.search')" @click="searchOpen = true">
      <span aria-hidden="true">⌕</span>
    </button>

    <nav class="sidebar-nav" :aria-label="t('shell.mainNav')">
      <ul class="primary-actions">
        <li><button type="button" class="nav-item" :title="t('shell.newChat')" @click="newChat"><span class="nav-glyph" aria-hidden="true">+</span><span v-if="!collapsed">{{ t('shell.newChat') }}</span></button></li>
        <li><button type="button" class="nav-item" disabled :title="`${t('shell.knowledge')}（${t('common.soon')}）`"><span class="nav-glyph" aria-hidden="true">▣</span><span v-if="!collapsed">{{ t('shell.knowledge') }}</span><span v-if="!collapsed" class="soon">{{ t('common.soon') }}</span></button></li>
        <li><button type="button" class="nav-item" disabled :title="`${t('shell.agents')}（${t('common.soon')}）`"><span class="nav-glyph" aria-hidden="true">✦</span><span v-if="!collapsed">{{ t('shell.agents') }}</span><span v-if="!collapsed" class="soon">{{ t('common.soon') }}</span></button></li>
        <li><button type="button" class="nav-item" :class="{ active: isActive('/space/organization') }" :aria-current="isActive('/space/organization') ? 'page' : undefined" :title="t('shell.sharedSpace')" @click="go('/space/organization')"><span class="nav-glyph" aria-hidden="true">∞</span><span v-if="!collapsed">{{ t('shell.sharedSpace') }}</span></button></li>
      </ul>

      <div v-if="!collapsed" class="space-picker">
        <label for="space-select">{{ t('shell.space') }}</label>
        <el-select id="space-select" :model-value="workspace.tenantId" :disabled="!workspace.tenants.length" :placeholder="t('shell.selectSpace')" @change="(value: string) => setTenant(value)">
          <el-option v-for="item in workspace.tenants" :key="item.id" :value="item.id" :label="item.via_organization ? `${item.name}（${t('shell.organizationSpace')}）` : item.name" />
        </el-select>
      </div>

      <!-- Recent sessions of the current space, grouped by last update. -->
      <section v-if="!collapsed" class="session-section" :aria-label="t('shell.recent')">
        <p v-if="workspace.sessionsError" class="session-error" role="alert">{{ workspace.sessionsError }}</p>
        <p v-else-if="!workspace.sessions.length" class="muted">{{ t('shell.noSessions') }}</p>
        <template v-for="group in groups" :key="group.key">
          <p class="nav-title">{{ group.label }}</p>
          <ul>
            <li v-for="session in group.items" :key="session.id">
              <button type="button" class="session-item" :class="{ selected: session.id === activeSession }" :aria-current="session.id === activeSession ? 'page' : undefined" :title="session.title" @click="openSession(session.id)">
                {{ session.title || t('common.unnamed') }}
              </button>
            </li>
          </ul>
        </template>
      </section>

      <template v-for="group in visibleGroups" :key="group.titleKey">
        <section class="nav-group">
          <h2 v-if="!collapsed" class="nav-title">{{ t(group.titleKey) }}</h2>
          <ul>
            <li v-for="item in group.items" :key="item.path">
              <button type="button" class="nav-item" :class="{ active: isActive(item.path) }" :aria-current="isActive(item.path) ? 'page' : undefined" :title="t(item.labelKey)" @click="go(item.path)">
                <span class="nav-glyph" aria-hidden="true">{{ t(item.labelKey).slice(0, 1) }}</span>
                <span v-if="!collapsed">{{ t(item.labelKey) }}</span>
              </button>
            </li>
          </ul>
        </section>
      </template>
    </nav>

    <div v-if="!collapsed" class="resize-handle" role="separator" aria-orientation="vertical" :aria-label="t('shell.resizeNav')" :aria-valuenow="width" :aria-valuemin="MIN_WIDTH" :aria-valuemax="MAX_WIDTH" tabindex="0" @pointerdown.prevent="onDragStart" @keydown="onSeparatorKey" />

    <div class="sidebar-user">
      <el-dropdown trigger="click" placement="top-start" @command="onUserCommand">
        <button type="button" class="user-button" :aria-label="t('shell.settings')">
          <span class="avatar" aria-hidden="true">{{ (workspace.user?.display_name || 'U').slice(0, 1) }}</span>
          <span v-if="!collapsed" class="user-text">
            <strong>{{ workspace.user?.display_name || t('shell.signedIn') }}</strong>
            <span v-if="workspace.user?.is_platform_admin" class="muted">{{ t('shell.platformAdmin') }}</span>
          </span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="item in LOCALES" :key="item.value" :command="item.value" :disabled="item.value === locale">{{ item.label }}</el-dropdown-item>
            <el-dropdown-item divided command="settings">{{ t('shell.settings') }}</el-dropdown-item>
            <el-dropdown-item command="signOut">{{ t('shell.signOut') }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <SessionSearch v-model="searchOpen" :sessions="workspace.sessions" @open="openSession" />
  </aside>
</template>

<style scoped>
.app-sidebar { position: sticky; top: 0; display: flex; flex-direction: column; gap: 12px; height: 100vh; width: 248px; padding: 12px; box-sizing: border-box; background: var(--surface); border-right: 1px solid var(--border); overflow: hidden; transition: width 0.2s ease; }
.app-sidebar--collapsed { width: 60px; }
.sidebar-head { display: flex; align-items: center; gap: 8px; min-height: 40px; }
.brand { display: inline-grid; place-items: center; width: 32px; height: 32px; border-radius: 8px; background: var(--el-color-primary); color: #fff; font-weight: 700; font-size: 13px; flex: none; }
.brand-name { flex: 1; font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.icon-button { width: 32px; height: 32px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); cursor: pointer; font-size: 16px; line-height: 1; flex: none; }
.icon-button--solo { margin: 0 auto; }
.space-picker { display: grid; gap: 6px; }
.space-picker label { font-size: 13px; color: var(--muted-text); }
.sidebar-nav { flex: 1; min-height: 0; overflow-y: auto; display: grid; gap: 12px; align-content: start; }
.primary-actions, .nav-group ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.nav-title { margin: 8px 0 4px; font-size: 12px; color: var(--muted-text); font-weight: 600; letter-spacing: 0.02em; }
.nav-item { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 40px; padding: 6px 10px; border: 0; border-radius: 6px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.nav-item:hover:not(:disabled) { background: var(--selected); }
.nav-item:disabled { color: var(--muted-text); cursor: not-allowed; }
.nav-item.active { background: var(--selected); color: var(--el-color-primary); font-weight: 600; }
.nav-item:focus-visible, .session-item:focus-visible, .icon-button:focus-visible, .user-button:focus-visible, .resize-handle:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
.nav-glyph { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 6px; background: var(--selected); font-size: 12px; flex: none; }
.soon { margin-left: auto; font-size: 12px; color: var(--muted-text); }
.session-section ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.session-item { width: 100%; min-height: 36px; padding: 6px 10px; border: 0; border-radius: 6px; background: transparent; font: inherit; font-size: 14px; text-align: left; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-item:hover, .session-item.selected { background: var(--selected); }
.session-error { color: var(--el-color-danger); font-size: 13px; }
.resize-handle { position: absolute; top: 0; right: -3px; bottom: 0; width: 6px; cursor: col-resize; }
.resize-handle:hover { background: var(--border); }
.sidebar-user { padding-top: 10px; border-top: 1px solid var(--border); }
.user-button { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 44px; padding: 4px; border: 0; border-radius: 6px; background: transparent; font: inherit; color: inherit; text-align: left; cursor: pointer; }
.user-button:hover { background: var(--selected); }
.avatar { display: inline-grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; background: var(--el-color-primary); color: #fff; font-weight: 600; flex: none; }
.user-text { display: grid; min-width: 0; }
.muted { color: var(--muted-text); font-size: 13px; }
@media (prefers-reduced-motion: reduce) { .app-sidebar { transition: none; } }
@media (max-width: 767px) { .app-sidebar { width: min(280px, 86vw) !important; } .resize-handle { display: none; } }
</style>
