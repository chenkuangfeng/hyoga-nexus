<script setup lang="ts">
import { ref } from 'vue'
import { authApi } from '../../api/auth'
import { errorMessageFor } from './loginErrors'
import { i18n } from '../../i18n'

const props = defineProps<{ error: string }>()
const emit = defineEmits<{ signedIn: [] }>()
const username = ref(''), password = ref(''), busy = ref(false), error = ref('')
async function submit() {
  if (busy.value || !username.value.trim() || !password.value) return
  busy.value = true; error.value = ''
  try { await authApi.login(username.value.trim(), password.value); password.value = ''; emit('signedIn') }
  catch (e) { error.value = e instanceof Error ? e.message : i18n.global.t('auth.loginIncomplete') }
  finally { password.value = ''; busy.value = false }
}
</script>
<template>
  <main class="login-page">
    <section class="login-card" aria-labelledby="login-title">
      <p class="eyebrow">HYOGA NEXUS</p>
      <h1 id="login-title">{{ $t('login.title') }}</h1>
      <el-alert v-if="props.error" :title="errorMessageFor(props.error)" type="warning" :closable="false" class="login-error" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="login-error" />
      <form @submit.prevent="submit">
        <label for="login-username">{{ $t('auth.username') }}</label>
        <el-input id="login-username" v-model="username" autocomplete="username" maxlength="128" :disabled="busy" />
        <label for="login-password">{{ $t('auth.password') }}</label>
        <el-input id="login-password" v-model="password" type="password" autocomplete="current-password" maxlength="256" show-password :disabled="busy" />
        <el-button type="primary" native-type="submit" :loading="busy" :disabled="!username.trim() || !password">{{ $t('auth.submit') }}</el-button>
      </form>
      <div class="divider"><span>{{ $t('auth.or') }}</span></div>
      <a class="wecom-link" :href="authApi.wecomLoginUrl">{{ $t('auth.wecomLogin') }}</a>
      <p class="intro">{{ $t('auth.intro') }}</p>
    </section>
  </main>
</template>
<style scoped>
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; box-sizing: border-box; }
.login-card { width: min(380px, 100%); display: grid; gap: 12px; }
.login-card form { display: grid; gap: 8px; }
.login-card label { font-size: 14px; color: var(--el-text-color-regular); }
.login-error { margin-bottom: 4px; }
.divider { text-align: center; color: var(--el-text-color-secondary); font-size: 13px; }
.wecom-link { display: block; text-align: center; padding: 10px; border: 1px solid var(--el-border-color); border-radius: 4px; color: var(--el-color-primary); text-decoration: none; }
.wecom-link:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 2px; }
</style>
