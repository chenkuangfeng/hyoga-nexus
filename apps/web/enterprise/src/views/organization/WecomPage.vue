<script setup lang="ts">
/** 企业微信绑定与应用目录；密钥仅在当前表单内存中，读取响应不含密钥。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { copyToClipboard } from '@nexus-web/core/utils/clipboard'
import { getEnterpriseWecom, requestEnterpriseWecomSync, saveEnterpriseWecom, type WecomConfig } from '@nexus-web/core/api/enterprise-wecom'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('org:manage'))
const config = ref<WecomConfig | null>(null), loading = ref(false), saving = ref(false), syncing = ref(false), error = ref(''), ready = ref(false)
const corpId = ref(''), callbackToken = ref(''), aesKey = ref('')
let epoch = 0
let pollGeneration = 0
let pollTimer: ReturnType<typeof setTimeout> | undefined
function stopPolling() { pollGeneration++; if (pollTimer) clearTimeout(pollTimer); pollTimer = undefined }
/** Read status only while queued, at most 12 times; never clear an in-progress credential form. */
function pollStatus(current: number, scope: string, remaining = 12) {
  stopPolling()
  if (!remaining || current !== epoch || !canManage.value || config.value?.sync_status !== 'requested') return
  const generation = pollGeneration
  pollTimer = setTimeout(async () => {
    try {
      const result = await getEnterpriseWecom(scope)
      if (current !== epoch || generation !== pollGeneration || scope !== tenant.value || !canManage.value) return
      config.value = result
      pollStatus(current, scope, remaining - 1)
    } catch { if (current === epoch && generation === pollGeneration) error.value = t('adminWecom.loadFailed') }
  }, 5000)
}
function clearSecrets() { callbackToken.value = ''; aesKey.value = '' }
function invalidate() { stopPolling(); epoch++; config.value = null; loading.value = false; saving.value = false; syncing.value = false; ready.value = false; error.value = ''; corpId.value = ''; clearSecrets() }
async function load() {
  stopPolling()
  const current = ++epoch, scope = tenant.value; ready.value = false; error.value = ''; config.value = null; corpId.value = ''; clearSecrets()
  if (!scope || !canManage.value) return
  loading.value = true
  try { const result = await getEnterpriseWecom(scope); if (current === epoch) { config.value = result; corpId.value = result.corp_id || ''; ready.value = true; pollStatus(current, scope) } }
  catch { if (current === epoch) error.value = t('adminWecom.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
const callbackReady = computed(() => !!config.value?.callback_configured)
const valid = computed(() => /^[A-Za-z0-9_-]{4,64}$/.test(corpId.value.trim()) && (!callbackToken.value || callbackToken.value.length <= 64) && (!aesKey.value || aesKey.value.length === 43))
async function save() {
  if (!canManage.value || !ready.value || saving.value || !valid.value) return
  const current = epoch, scope = tenant.value
  stopPolling(); saving.value = true; error.value = ''
  try {
    const result = await saveEnterpriseWecom(scope, { corp_id: corpId.value.trim(), ...(callbackToken.value ? { callback_token: callbackToken.value } : {}), ...(aesKey.value ? { encoding_aes_key: aesKey.value } : {}) })
    if (current !== epoch || !canManage.value) return
    config.value = result; corpId.value = result.corp_id || ''; clearSecrets(); MessagePlugin.success(t('adminWecom.saved'))
  } catch { if (current === epoch) error.value = t('adminWecom.saveFailed') }
  finally { if (current === epoch) { saving.value = false; pollStatus(current, scope) } }
}
async function syncNow() {
  if (!canManage.value || !ready.value || !config.value?.configured || saving.value || syncing.value || config.value.sync_status === 'requested') return
  const current = epoch, scope = tenant.value; syncing.value = true; error.value = ''
  try { await requestEnterpriseWecomSync(scope); if (current !== epoch) return; syncing.value = false; MessagePlugin.success(t('adminWecom.syncQueued')); await load() }
  catch { if (current === epoch) error.value = t('adminWecom.syncFailed') }
  finally { if (current === epoch) syncing.value = false }
}
async function copyPath(path: string | null) {
  if (!path) return
  const ok = await copyToClipboard(new URL(path, window.location.origin).toString())
  MessagePlugin[ok ? 'success' : 'error'](t(ok ? 'adminWecom.copied' : 'adminWecom.copyFailed'))
}
function purpose(value: string) { return t(`adminWecom.purpose.${value}`) }
function status(value: string) { return t(`adminWecom.syncStatus.${value}`, value) }
</script>

<template>
  <section class="wecom-page">
    <header class="section-header"><div><h2>{{ t('adminWecom.title') }}</h2><p>{{ t('adminWecom.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="saving || syncing" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading"><template v-if="ready && config">
        <section class="wecom-card">
          <header><div><h3>{{ t('adminWecom.corpTitle') }}</h3><p>{{ t(config.configured ? 'adminWecom.corpBound' : 'adminWecom.corpUnbound') }}</p></div><t-tag v-if="config.configured" theme="success" variant="light">{{ config.corp_id }}</t-tag></header>
          <div class="fields"><label>{{ t('adminWecom.corpId') }}<t-input v-model="corpId" :maxlength="64" :disabled="saving || config.configured" :placeholder="t('adminWecom.corpIdHint')" /></label><label>{{ t('adminWecom.callbackToken') }}<t-input v-model="callbackToken" type="password" :maxlength="64" :disabled="saving" :placeholder="callbackReady ? t('adminWecom.keepSecret') : t('adminWecom.callbackTokenHint')" /></label><label>{{ t('adminWecom.aesKey') }}<t-input v-model="aesKey" type="password" :maxlength="43" :disabled="saving" :placeholder="callbackReady ? t('adminWecom.keepSecret') : t('adminWecom.aesKeyHint')" /></label></div>
          <div class="actions"><span v-if="config.configured" class="callback-state">{{ t(callbackReady ? 'adminWecom.callbackReady' : 'adminWecom.callbackMissing') }}</span><span class="spacer" /><t-button theme="primary" :loading="saving" :disabled="saving || !valid || (!config.configured && !corpId.trim())" @click="save">{{ t('adminWecom.saveCorp') }}</t-button></div>
        </section>
        <section v-if="config.configured" class="wecom-card">
          <header><div><h3>{{ t('adminWecom.directoryTitle') }}</h3><p>{{ t('adminWecom.syncStatusLabel') }}：{{ status(config.sync_status || 'never') }}<span v-if="config.synced_at"> · {{ config.synced_at }}</span></p><p v-if="config.sync_error" class="sync-error">{{ config.sync_error }}</p></div><t-button variant="outline" :loading="syncing" :disabled="syncing || saving || config.sync_status === 'requested'" @click="syncNow">{{ t('adminWecom.syncNow') }}</t-button></header>
          <div class="callback-row"><div><strong>{{ t('adminWecom.callbackAddress') }}</strong><code>{{ config.callback_path }}</code></div><t-button variant="text" @click="copyPath(config.callback_path)">{{ t('adminWecom.copy') }}</t-button></div>
        </section>
        <section v-if="config.configured" class="wecom-card"><header><div><h3>{{ t('adminWecom.appsTitle') }}</h3><p>{{ t('adminWecom.appsHint') }}</p></div></header>
          <div class="table-shell"><table><thead><tr><th>{{ t('adminWecom.appName') }}</th><th>{{ t('adminWecom.purposeLabel') }}</th><th>{{ t('adminWecom.agentId') }}</th><th>{{ t('adminWecom.qrLogin') }}</th><th>{{ t('adminWecom.appStatus') }}</th><th>{{ t('adminWecom.homepage') }}</th></tr></thead><tbody><tr v-for="app in config.apps" :key="app.id"><td>{{ app.name }}</td><td>{{ purpose(app.purpose) }}</td><td>{{ app.wecom_agentid }}</td><td><t-tag :theme="app.qr_login ? 'success' : 'default'" variant="light">{{ t(app.qr_login ? 'adminWecom.enabled' : 'adminWecom.disabled') }}</t-tag></td><td>{{ t(`adminWecom.appState.${app.status}`) }}</td><td><div class="entry-cell"><code>{{ app.entry_path }}</code><t-button variant="text" @click="copyPath(app.entry_path)">{{ t('adminWecom.copy') }}</t-button></div></td></tr><tr v-if="!config.apps.length"><td colspan="6">{{ t('adminWecom.noApps') }}</td></tr></tbody></table></div>
        </section>
      </template></t-loading>
    </template>
  </section>
</template>

<style scoped>
.wecom-page { min-width: 0; }
.wecom-card { margin-top: 20px; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.wecom-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.wecom-card h3 { margin: 0 0 6px; }
.wecom-card p { margin: 0; color: var(--td-text-color-secondary); }
.wecom-card .sync-error { margin-top: 8px; color: var(--td-error-color); }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 16px; }
.fields label { display: grid; gap: 8px; min-width: 0; }
.fields :deep(.t-input) { width: 100%; }
.actions, .entry-cell { display: flex; align-items: center; gap: 8px; }
.actions { margin-top: 16px; }
.spacer { flex: 1; }
.callback-state { color: var(--td-text-color-secondary); }
.callback-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-top: 16px; border-top: 1px solid var(--td-component-stroke); }
.callback-row > div { display: grid; gap: 8px; min-width: 0; }
code { overflow-wrap: anywhere; color: var(--td-text-color-secondary); }
.table-shell { max-width: 100%; overflow-x: auto; }
table { width: 100%; min-width: 780px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
.entry-cell { min-width: 220px; }
@media (max-width: 600px) { .wecom-card { padding: 16px; } .wecom-card > header { flex-direction: column; } }
</style>
