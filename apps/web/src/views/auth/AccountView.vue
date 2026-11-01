<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { authApi, type CurrentUser } from '../../api/auth'
import { i18n } from '../../i18n'

const props = defineProps<{ user: CurrentUser; wecomResult: string }>()
const emit = defineEmits<{ signedOut: [] }>()
const busy = ref(false), error = ref(''), feedback = ref('')
const form = reactive({ current: '', next: '', confirm: '' })
const bindMessages: Record<string, string> = {
  bound: i18n.global.t('auth.bound'), conflict: i18n.global.t('auth.conflict'), unbound: i18n.global.t('auth.bindUnbound'),
  failed: i18n.global.t('auth.bindFailed'), unauthenticated: i18n.global.t('auth.bindUnauthenticated'),
}
onMounted(() => { if (props.wecomResult) feedback.value = bindMessages[props.wecomResult] || '' })

async function changePassword() {
  if (busy.value) return
  if (form.next.length < 10) { error.value = i18n.global.t('auth.passwordTooShort'); return }
  if (form.next !== form.confirm) { error.value = i18n.global.t('auth.passwordMismatch'); return }
  busy.value = true; error.value = ''; feedback.value = ''
  try { await authApi.changePassword(form.current, form.next); emit('signedOut') }
  catch (e) { error.value = e instanceof Error ? e.message : i18n.global.t('auth.passwordFailed') }
  finally { Object.assign(form, { current: '', next: '', confirm: '' }); busy.value = false }
}
async function bindWecom() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { window.location.href = await authApi.wecomBindStart() }
  catch (e) { error.value = e instanceof Error ? e.message : i18n.global.t('auth.bindStartFailed'); busy.value = false }
}
</script>
<template>
  <main class="account-page">
    <header><div><p class="eyebrow">{{ $t('auth.eyebrow') }}</p><h1>{{ $t('shell.titles.personalAccount') }}</h1></div></header>
    <p class="intro">{{ $t('auth.currentAccount', { name: props.user.display_name || $t('common.unnamed'), methods: props.user.providers.map(p => p === 'password' ? $t('auth.methodPassword') : p === 'wecom' ? $t('auth.methodWecom') : p).join($t('auth.methodSeparator')) }) }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>
    <section class="settings-section" aria-labelledby="wecom-title">
      <h2 id="wecom-title">{{ $t('auth.wecomTitle') }}</h2>
      <p class="intro">{{ $t('auth.wecomIntro') }}</p>
      <el-button :disabled="busy || props.user.providers.includes('wecom')" @click="bindWecom">
        {{ props.user.providers.includes('wecom') ? $t('auth.wecomBound') : $t('auth.wecomBind') }}
      </el-button>
    </section>
    <section class="settings-section" aria-labelledby="password-title">
      <h2 id="password-title">{{ $t('auth.passwordTitle') }}</h2>
      <p class="intro">{{ $t('auth.passwordIntro') }}</p>
      <form class="password-form" @submit.prevent="changePassword">
        <label for="account-current">{{ $t('auth.currentPassword') }}</label>
        <el-input id="account-current" v-model="form.current" type="password" autocomplete="current-password" show-password :disabled="busy" />
        <label for="account-next">{{ $t('auth.newPassword') }}</label>
        <el-input id="account-next" v-model="form.next" type="password" autocomplete="new-password" show-password :disabled="busy" />
        <label for="account-confirm">{{ $t('auth.confirmPassword') }}</label>
        <el-input id="account-confirm" v-model="form.confirm" type="password" autocomplete="new-password" show-password :disabled="busy" />
        <el-button type="primary" native-type="submit" :disabled="busy || !form.current || !form.next">{{ $t('auth.changePassword') }}</el-button>
      </form>
    </section>
  </main>
</template>
<style scoped>
.account-page { max-width: 640px; margin: 0 auto; padding: 24px; display: grid; gap: 12px; }
.password-form { display: grid; gap: 8px; max-width: 420px; }
.password-form label { font-size: 14px; color: var(--el-text-color-regular); }
</style>
