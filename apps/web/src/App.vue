<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { authApi, type CurrentUser } from './api/auth'
import { AUTH_REQUIRED_EVENT } from './api/chat'
import OverviewView from './views/OverviewView.vue'
import ConversationView from './views/chat/ConversationView.vue'
import NativeSettingsView from './views/settings/NativeSettingsView.vue'
import ModelSettingsView from './views/settings/ModelSettingsView.vue'
import RoleManagementView from './views/settings/RoleManagementView.vue'
import LoginView from './views/auth/LoginView.vue'
import AccountView from './views/auth/AccountView.vue'

/** Hash routes: `#page?query`. Query values only carry result keys set by the server redirects. */
const pages = ['chat', 'settings', 'roles', 'account', 'native-settings', 'overview'] as const
type Page = typeof pages[number]
const hashPath = () => location.hash.replace(/^#/, '').split('?')[0]
const hashQuery = (key: string) => new URLSearchParams(location.hash.split('?')[1] || '').get(key) || ''
const currentPage = (): Page => (pages as readonly string[]).includes(hashPath()) ? hashPath() as Page : 'chat'
const page = ref<Page>(currentPage())
const status = ref<'checking' | 'anonymous' | 'signed-in'>('checking')
const user = ref<CurrentUser | null>(null)
const loginError = ref('')
const wecomResult = ref('')
function select(value: Page) { page.value = value; location.hash = value }
const hashChanged = () => { page.value = currentPage(); loginError.value = hashQuery('error'); wecomResult.value = hashQuery('wecom') }
async function refreshSession() {
  try {
    user.value = await authApi.me()
    status.value = user.value ? 'signed-in' : 'anonymous'
  } catch { status.value = 'anonymous' }
}
function signedIn() { void refreshSession().then(() => { if (status.value === 'signed-in') select('chat') }) }
function signedOut() { user.value = null; status.value = 'anonymous'; location.hash = '#login' }
async function logout() { try { await authApi.logout() } finally { signedOut() } }
const sessionLost = () => { if (status.value !== 'anonymous') signedOut() }
onMounted(() => {
  hashChanged()
  window.addEventListener('hashchange', hashChanged)
  window.addEventListener(AUTH_REQUIRED_EVENT, sessionLost)
  void refreshSession()
})
onBeforeUnmount(() => {
  window.removeEventListener('hashchange', hashChanged)
  window.removeEventListener(AUTH_REQUIRED_EVENT, sessionLost)
})
</script>
<template>
  <template v-if="status === 'signed-in' && user">
    <nav class="app-navigation" aria-label="主导航">
      <button type="button" :aria-current="page === 'chat' ? 'page' : undefined" @click="select('chat')">对话工作台</button>
      <button type="button" :aria-current="page === 'settings' ? 'page' : undefined" @click="select('settings')">用户设置</button>
      <button type="button" :aria-current="page === 'roles' ? 'page' : undefined" @click="select('roles')">角色与权限</button>
      <button type="button" :aria-current="page === 'native-settings' ? 'page' : undefined" @click="select('native-settings')">Native 与记忆</button>
      <button type="button" :aria-current="page === 'account' ? 'page' : undefined" @click="select('account')">我的账号</button>
      <button type="button" :aria-current="page === 'overview' ? 'page' : undefined" @click="select('overview')">平台能力</button>
      <button type="button" class="logout" @click="logout">退出登录</button>
    </nav>
    <ConversationView v-if="page === 'chat'" /><ModelSettingsView v-else-if="page === 'settings'" />
    <RoleManagementView v-else-if="page === 'roles'" />
    <AccountView v-else-if="page === 'account'" :user="user" :wecom-result="wecomResult" @signed-out="signedOut" />
    <NativeSettingsView v-else-if="page === 'native-settings'" /><OverviewView v-else />
  </template>
  <p v-else-if="status === 'checking'" class="session-checking" role="status">正在确认登录状态…</p>
  <LoginView v-else :error="loginError" @signed-in="signedIn" />
</template>
<style scoped>
.logout { margin-left: auto; }
.session-checking { padding: 24px; }
</style>
