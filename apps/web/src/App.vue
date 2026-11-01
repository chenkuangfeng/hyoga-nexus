<script setup lang="ts">
/**
 * Session gate. Signed-in users get the workbench shell (sidebar + routed page); everyone else sees
 * the login form at whatever path they opened, and returns to /chat after signing in.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import { i18n } from './i18n'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from './api/auth'
import { AUTH_REQUIRED_EVENT } from './api/chat'
import AppLayout from './layouts/AppLayout.vue'
import LoginView from './views/auth/LoginView.vue'
import { loadTenants, workspace } from './stores/workspace'

const route = useRoute()
const router = useRouter()
const status = ref<'checking' | 'anonymous' | 'signed-in'>('checking')
const loginError = computed(() => String(route.query.error || ''))
// Element Plus's own strings (date pickers, dialogs, empty states) follow the interface language.
const elLocale = computed(() => (i18n.global.locale.value === 'en-US' ? en : zhCn))

async function refreshSession() {
  try {
    workspace.user = await authApi.me()
    status.value = workspace.user ? 'signed-in' : 'anonymous'
    if (status.value === 'signed-in') await loadTenants()
  } catch { workspace.user = null; status.value = 'anonymous' }
}
async function signedIn() {
  await refreshSession()
  if (status.value === 'signed-in') void router.replace('/chat')
}
function signedOut() {
  workspace.user = null; workspace.sessions = []; workspace.tenants = []
  status.value = 'anonymous'
  void router.replace({ path: '/login' })
}
async function logout() { try { await authApi.logout() } finally { signedOut() } }
const sessionLost = () => { if (status.value !== 'anonymous') signedOut() }

onMounted(() => {
  window.addEventListener(AUTH_REQUIRED_EVENT, sessionLost)
  void refreshSession()
})
onBeforeUnmount(() => window.removeEventListener(AUTH_REQUIRED_EVENT, sessionLost))
</script>

<template>
  <el-config-provider :locale="elLocale">
    <AppLayout v-if="status === 'signed-in'" @sign-out="logout" />
    <p v-else-if="status === 'checking'" class="session-checking" role="status">{{ $t('shell.sessionChecking') }}</p>
    <LoginView v-else :error="loginError" @signed-in="signedIn" />
  </el-config-provider>
</template>

<style scoped>
.session-checking { padding: 24px; }
</style>
