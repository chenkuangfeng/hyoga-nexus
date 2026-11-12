<template>
  <main class="change-password-page">
    <section class="change-password-card">
      <h1>{{ t('changePassword.title') }}</h1>
      <p class="change-password-description">{{ t('changePassword.description') }}</p>
      <t-form ref="formRef" :data="form" :rules="rules" layout="vertical" @submit="handleSubmit">
        <t-form-item :label="t('changePassword.current')" name="current_password">
          <t-input v-model="form.current_password" type="password" autocomplete="current-password" />
        </t-form-item>
        <t-form-item :label="t('changePassword.next')" name="new_password">
          <t-input v-model="form.new_password" type="password" autocomplete="new-password" />
        </t-form-item>
        <t-form-item :label="t('changePassword.confirm')" name="confirm_password">
          <t-input v-model="form.confirm_password" type="password" autocomplete="new-password" />
        </t-form-item>
        <t-button type="submit" theme="primary" block :loading="loading">
          {{ t('changePassword.submit') }}
        </t-button>
      </t-form>
    </section>
  </main>
</template>

<script setup lang="ts">
// Shown after sign-in when the account still has a temporary password (`user.must_change_password`).
// The backend allows only this route, /auth/me and sign-out until the password is changed, so the
// user is sent back to the login page afterwards and signs in with the new password.
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import { post } from '@nexus-web/core/utils/request'
import { useAuthStore } from '@nexus-web/core/stores/auth'

const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const formRef = ref<any>(null)
const loading = ref(false)
const form = reactive({ current_password: '', new_password: '', confirm_password: '' })

const rules = {
  current_password: [{ required: true, message: t('changePassword.current'), type: 'error' }],
  new_password: [{ required: true, min: 10, message: t('changePassword.next'), type: 'error' }],
  confirm_password: [{ required: true, message: t('changePassword.confirm'), type: 'error' }],
}

const handleSubmit = async ({ validateResult }: { validateResult: unknown }) => {
  if (validateResult !== true) return
  if (form.new_password !== form.confirm_password) {
    MessagePlugin.error(t('changePassword.mismatch'))
    return
  }
  loading.value = true
  try {
    await post('/api/v1/auth/change-password', {
      current_password: form.current_password,
      new_password: form.new_password,
    })
    MessagePlugin.success(t('changePassword.success'))
    // Every session is revoked by the server, so the local token is dropped as well.
    authStore.logout()
    router.replace('/login')
  } catch (error: any) {
    MessagePlugin.error(error?.message || t('changePassword.failed'))
  } finally {
    loading.value = false
  }
}
</script>

<style scoped lang="less">
.change-password-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.change-password-card {
  width: 100%;
  max-width: 420px;
}

.change-password-description {
  margin: 8px 0 20px;
  color: var(--td-text-color-secondary);
}
</style>
