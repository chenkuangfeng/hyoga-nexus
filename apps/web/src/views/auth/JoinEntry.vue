<template>
  <main class="join-entry">
    <section class="join-card">
      <div v-if="busy" class="join-loading">
        <t-loading size="small" />
        <span>{{ t('joinLink.joining') }}</span>
      </div>
      <template v-else>
        <h1>{{ t('joinLink.failedTitle') }}</h1>
        <p class="join-message">{{ t('joinLink.failedBody') }}</p>
        <t-button theme="primary" @click="router.replace('/platform/shared-spaces')">
          {{ t('joinLink.backToSpaces') }}
        </t-button>
      </template>
    </section>
  </main>
</template>

<script setup lang="ts">
// `/join` entry point for invitations:
// - `?code=` is a shared-space invite code: open the shared-space page with it.
// - `?token=` is an enterprise share link: signed-in users join the space and enter it; signed-out users
//   sign in first, and the link is picked up again after sign-in (see Login.vue).
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import {
  rememberPendingInviteCode,
  rememberPendingInviteToken,
  takePendingInviteCode,
  takePendingInviteToken,
} from '@/utils/pendingInvite'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const busy = ref(true)

function sharedSpaceWithCode(code: string) {
  return router.replace({ path: '/platform/shared-spaces', query: { invite_code: code } })
}

onMounted(async () => {
  const queryCode = typeof route.query.code === 'string' ? route.query.code.trim() : ''
  const queryToken = typeof route.query.token === 'string' ? route.query.token.trim() : ''

  // Signed out: keep the invitation for after sign-in. Login.vue sends the user back here.
  if (!authStore.isLoggedIn) {
    if (queryToken) rememberPendingInviteToken(queryToken)
    if (queryCode) rememberPendingInviteCode(queryCode)
    await router.replace('/login')
    return
  }

  if (queryCode) {
    await sharedSpaceWithCode(queryCode)
    return
  }
  const token = queryToken || takePendingInviteToken()
  if (!token) {
    const pendingCode = takePendingInviteCode()
    await (pendingCode ? sharedSpaceWithCode(pendingCode) : router.replace('/platform/shared-spaces'))
    return
  }
  const result = await authStore.acceptInvitationByTokenAndRefresh(token)
  if (result.ok) {
    MessagePlugin.success(t('joinLink.joined', { name: result.tenantName ?? '' }))
    await router.replace('/platform/knowledge-bases')
    return
  }
  busy.value = false
})
</script>

<style scoped lang="less">
.join-entry {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px 20px;
  background: var(--td-bg-color-page);
}

.join-card {
  width: min(460px, 100%);
  padding: 40px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 20px;
  background: var(--td-bg-color-container);
  text-align: center;
}

h1 {
  margin: 0 0 12px;
  font-size: var(--app-text-4xl);
}

.join-message {
  margin: 0 0 24px;
  color: var(--td-text-color-secondary);
  line-height: 1.6;
}

.join-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--td-text-color-secondary);
}
</style>
