<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { authApi, type CurrentUser } from '../../api/auth'

const props = defineProps<{ user: CurrentUser; wecomResult: string }>()
const emit = defineEmits<{ signedOut: [] }>()
const busy = ref(false), error = ref(''), feedback = ref('')
const form = reactive({ current: '', next: '', confirm: '' })
const bindMessages: Record<string, string> = {
  bound: '企业微信已绑定。', conflict: '该企业微信账号已绑定其他用户。', unbound: '请先登录后再绑定。',
  failed: '企业微信绑定未完成，请重新操作。', unauthenticated: '登录已失效，请重新登录后绑定。',
}
onMounted(() => { if (props.wecomResult) feedback.value = bindMessages[props.wecomResult] || '' })

async function changePassword() {
  if (busy.value) return
  if (form.next.length < 10) { error.value = '新密码至少 10 个字符'; return }
  if (form.next !== form.confirm) { error.value = '两次输入的新密码不一致'; return }
  busy.value = true; error.value = ''; feedback.value = ''
  try { await authApi.changePassword(form.current, form.next); emit('signedOut') }
  catch (e) { error.value = e instanceof Error ? e.message : '密码未修改' }
  finally { Object.assign(form, { current: '', next: '', confirm: '' }); busy.value = false }
}
async function bindWecom() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { window.location.href = await authApi.wecomBindStart() }
  catch (e) { error.value = e instanceof Error ? e.message : '无法开始绑定'; busy.value = false }
}
</script>
<template>
  <main class="account-page">
    <header><div><p class="eyebrow">HYOGA NEXUS / 账号</p><h1>我的账号</h1></div></header>
    <p class="intro">当前账号：{{ props.user.display_name || '未命名' }}。已关联的登录方式：{{ props.user.providers.map(p => p === 'password' ? '账号密码' : p === 'wecom' ? '企业微信' : p).join('、') }}。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p class="feedback" role="status" aria-live="polite">{{ feedback }}</p>
    <section class="settings-section" aria-labelledby="wecom-title">
      <h2 id="wecom-title">企业微信</h2>
      <p class="intro">绑定后可使用企业微信扫码登录。每个企业微信账号只能绑定一个用户。</p>
      <el-button :disabled="busy || props.user.providers.includes('wecom')" @click="bindWecom">
        {{ props.user.providers.includes('wecom') ? '已绑定企业微信' : '绑定企业微信' }}
      </el-button>
    </section>
    <section class="settings-section" aria-labelledby="password-title">
      <h2 id="password-title">修改密码</h2>
      <p class="intro">修改后所有设备上的登录都会失效，需要重新登录。</p>
      <form class="password-form" @submit.prevent="changePassword">
        <label for="account-current">当前密码</label>
        <el-input id="account-current" v-model="form.current" type="password" autocomplete="current-password" show-password :disabled="busy" />
        <label for="account-next">新密码（至少 10 个字符）</label>
        <el-input id="account-next" v-model="form.next" type="password" autocomplete="new-password" show-password :disabled="busy" />
        <label for="account-confirm">确认新密码</label>
        <el-input id="account-confirm" v-model="form.confirm" type="password" autocomplete="new-password" show-password :disabled="busy" />
        <el-button type="primary" native-type="submit" :disabled="busy || !form.current || !form.next">修改密码</el-button>
      </form>
    </section>
  </main>
</template>
<style scoped>
.account-page { max-width: 640px; margin: 0 auto; padding: 24px; display: grid; gap: 12px; }
.password-form { display: grid; gap: 8px; max-width: 420px; }
.password-form label { font-size: 14px; color: var(--el-text-color-regular); }
</style>
