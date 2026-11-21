<script setup lang="ts">
/** 管理端处理 worker 中断后遗留的 unknown 会话阻塞；解除不会重放 Run。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { listSessions, listUnknownAdmissions, resolveUnknownRun, type SessionView, type UnknownAdmission } from '@nexus-web/core/api/native-runs'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.ready && (auth.currentTenantRole === 'owner' || auth.currentTenantRole === 'admin'))
const rows = ref<UnknownAdmission[]>([]), sessions = ref<SessionView[]>([]), loading = ref(false), busy = ref(''), error = ref(''), ready = ref(false)
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
function current(request: number, scope: string, user: string, revision: number) { return request === epoch && scope === tenant.value && user === String(auth.user?.id || '') && revision === context.revision && canManage.value }
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; sessions.value = []; loading.value = false; busy.value = ''; error.value = ''; ready.value = false }
async function load() {
  invalidate()
  if (!tenant.value || !canManage.value) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  loading.value = true
  try {
    const [unknown, sessionRows] = await Promise.all([listUnknownAdmissions(scope), listSessions(scope)])
    if (current(request, scope, user, revision)) { rows.value = unknown; sessions.value = sessionRows; ready.value = true }
  } catch { if (current(request, scope, user, revision)) error.value = t('adminRuntime.loadFailed') }
  finally { if (current(request, scope, user, revision)) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${auth.currentTenantRole || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
function sessionTitle(row: UnknownAdmission) { return sessions.value.find(session => session.id === row.session_id)?.title || row.session_id }
function resolve(row: UnknownAdmission) {
  if (!canManage.value || !ready.value || busy.value || !rows.value.includes(row) || confirmation) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t(row.safe ? 'adminRuntime.resolveSafeTitle' : 'adminRuntime.resolveUnsafeTitle'), body: t(row.safe ? 'adminRuntime.resolveSafeConfirm' : 'adminRuntime.resolveUnsafeConfirm', { session: sessionTitle(row) }), theme: row.safe ? 'default' : 'warning',
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (!current(request, scope, user, revision)) return
      busy.value = row.run_id; error.value = ''
      try { await resolveUnknownRun(scope, row.run_id); if (!current(request, scope, user, revision)) return; rows.value = rows.value.filter(item => item.run_id !== row.run_id); MessagePlugin.success(t('adminRuntime.resolved')) }
      catch { if (current(request, scope, user, revision)) error.value = t('adminRuntime.resolveFailed') }
      finally { if (request === epoch) busy.value = '' }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
</script>

<template>
  <section class="runtime-health-page">
    <header class="section-header"><div><h2>{{ t('adminRuntime.title') }}</h2><p>{{ t('adminRuntime.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="!!busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminRuntime.scopeHint')" /><t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading"><div v-if="ready" class="table-shell"><table><thead><tr><th>{{ t('adminRuntime.session') }}</th><th>{{ t('adminRuntime.run') }}</th><th>{{ t('adminRuntime.interrupted') }}</th><th>{{ t('adminRuntime.status') }}</th><th>{{ t('adminRuntime.safety') }}</th><th>{{ t('adminRuntime.actions') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.run_id"><td>{{ sessionTitle(row) }}</td><td><code>{{ row.run_id }}</code></td><td>{{ row.interrupted_at }}</td><td>{{ row.run_status }}</td><td><t-tag :theme="row.safe ? 'success' : 'warning'" variant="light">{{ t(row.safe ? 'adminRuntime.safe' : 'adminRuntime.uncertain') }}</t-tag></td><td><t-button theme="primary" variant="outline" :loading="busy === row.run_id" :disabled="!!busy" @click="resolve(row)">{{ t('adminRuntime.resolve') }}</t-button></td></tr><tr v-if="!rows.length"><td colspan="6">{{ t('adminRuntime.empty') }}</td></tr></tbody></table></div></t-loading>
    </template>
  </section>
</template>

<style scoped>
.runtime-health-page { min-width: 0; }
.table-shell { max-width: 100%; overflow-x: auto; margin-top: 16px; }
table { width: 100%; min-width: 820px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); vertical-align: top; overflow-wrap: anywhere; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
code { font-size: var(--app-text-xs); }
</style>
