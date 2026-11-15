<script setup lang="ts">
/** 企业 Token 用量与月度上限；金额并非现有服务端统计的一部分。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getEnterpriseUsage, listEnterpriseUsageLimits, saveEnterpriseUsageLimit, type EnterpriseUsageLimit, type EnterpriseUsageRow, type UsageGroup } from '@nexus-web/core/api/enterprise-usage'
import { listEnterpriseMembers, type EnterpriseMember } from '@nexus-web/core/api/enterprise-members'
import { listOrganizationUnits, type OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'
import { useAdminContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('models:manage'))
function today() { const date = new Date(); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}` }
function monthStart() { return `${today().slice(0, 7)}-01` }
const start = ref(monthStart()), end = ref(today()), groupBy = ref<UsageGroup>('day')
const rows = ref<EnterpriseUsageRow[]>([]), limits = ref<EnterpriseUsageLimit[]>([]), members = ref<EnterpriseMember[]>([]), units = ref<OrganizationNode[]>([])
const loading = ref(false), saving = ref(false), ready = ref(false), error = ref(''), limitValue = ref<number | undefined>(), scopeChoice = ref('tenant')
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const groupOptions = computed(() => [{ value: 'day', label: t('adminUsage.byDay') }, ...(context.can('members:manage') ? [{ value: 'user', label: t('adminUsage.byMember') }] : []), ...(context.can('org:manage') ? [{ value: 'org_unit', label: t('adminUsage.byDepartment') }] : [])])
const scopeOptions = computed(() => [{ value: 'tenant', label: t('adminUsage.enterprise') }, ...(context.can('org:manage') ? units.value.map(row => ({ value: `org_unit:${row.id}`, label: `${t('adminUsage.department')}: ${row.name}` })) : []), ...(context.can('members:manage') ? members.value.map(row => ({ value: `user:${row.user_id}`, label: `${t('adminUsage.member')}: ${row.display_name || row.username || row.email || row.user_id}` })) : [])])
const memberNames = computed(() => new Map(members.value.map(row => [row.user_id, row.display_name || row.username || row.email || row.user_id])))
const unitNames = computed(() => new Map(units.value.map(row => [row.id, row.name])))
const totalInput = computed(() => rows.value.reduce((sum, row) => sum + row.input_tokens, 0)), totalOutput = computed(() => rows.value.reduce((sum, row) => sum + row.output_tokens, 0)), totalRuns = computed(() => rows.value.reduce((sum, row) => sum + row.runs, 0))
function validDate(value: string) { return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value }
const validDates = computed(() => validDate(start.value) && validDate(end.value) && start.value <= end.value)
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; limits.value = []; members.value = []; units.value = []; ready.value = false; loading.value = false; saving.value = false; error.value = ''; limitValue.value = undefined; scopeChoice.value = 'tenant' }
function labelForLimit(row: EnterpriseUsageLimit) { return row.scope_kind === 'tenant' ? t('adminUsage.enterprise') : row.scope_kind === 'user' ? memberNames.value.get(row.scope_id) || row.scope_id : unitNames.value.get(row.scope_id) || row.scope_id }
async function load() {
  invalidate()
  if (!canManage.value || !tenant.value) return
  if (!validDates.value) { error.value = t('adminUsage.invalidDates'); return }
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  loading.value = true
  try {
    const [report, savedLimits] = await Promise.all([getEnterpriseUsage(scope, groupBy.value, start.value, end.value), listEnterpriseUsageLimits(scope)])
    if (request !== epoch || scope !== tenant.value || user !== String(auth.user?.id || '') || revision !== context.revision || !canManage.value) return
    rows.value = report; limits.value = savedLimits; ready.value = true
    const optional: Promise<void>[] = []
    if (context.can('members:manage')) optional.push(listEnterpriseMembers(scope).then(value => { if (request === epoch) members.value = value }).catch(() => undefined))
    if (context.can('org:manage')) optional.push(listOrganizationUnits(scope).then(value => { if (request === epoch) units.value = value }).catch(() => undefined))
    await Promise.all(optional)
  } catch { if (request === epoch) error.value = t('adminUsage.loadFailed') }
  finally { if (request === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
watch(groupOptions, choices => { if (!choices.some(option => option.value === groupBy.value)) groupBy.value = 'day' })
function rowKey(key: string) { return groupBy.value === 'day' ? key : groupBy.value === 'user' ? memberNames.value.get(key) || key : unitNames.value.get(key) || key }
function addLimit() {
  if (!canManage.value || saving.value || loading.value || !ready.value || !Number.isSafeInteger(limitValue.value) || !limitValue.value || limitValue.value < 1) return
  const [kind, id] = scopeChoice.value.includes(':') ? scopeChoice.value.split(':', 2) : ['tenant', '']
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminUsage.saveTitle'), body: t('adminUsage.saveConfirm', { scope: scopeOptions.value.find(item => item.value === scopeChoice.value)?.label || scopeChoice.value, tokens: limitValue.value }),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (request !== epoch || scope !== tenant.value || user !== String(auth.user?.id || '') || revision !== context.revision || !canManage.value) return
      saving.value = true; error.value = ''
      try { await saveEnterpriseUsageLimit(scope, kind as EnterpriseUsageLimit['scope_kind'], id || null, limitValue.value!); if (request !== epoch) return; MessagePlugin.success(t('adminUsage.saved')); limitValue.value = undefined; await load() }
      catch { if (request === epoch) error.value = t('adminUsage.saveFailed') }
      finally { if (request === epoch) saving.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
function removeLimit(row: EnterpriseUsageLimit) {
  if (!canManage.value || saving.value || !limits.value.includes(row)) return
  const request = epoch, scope = tenant.value, user = String(auth.user?.id || ''), revision = context.revision
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminUsage.removeTitle'), body: t('adminUsage.removeConfirm', { scope: labelForLimit(row) }), theme: 'warning', onConfirm: async () => {
    if (confirmation !== dialog) return
    dialog.hide(); confirmation = undefined
    if (request !== epoch || scope !== tenant.value || user !== String(auth.user?.id || '') || revision !== context.revision || !canManage.value) return
    saving.value = true; error.value = ''
    try { await saveEnterpriseUsageLimit(scope, row.scope_kind, row.scope_kind === 'tenant' ? null : row.scope_id, null); if (request !== epoch) return; MessagePlugin.success(t('adminUsage.removed')); await load() }
    catch { if (request === epoch) error.value = t('adminUsage.removeFailed') }
    finally { if (request === epoch) saving.value = false }
  }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined } })
  confirmation = dialog
}
</script>

<template>
  <section class="usage-page">
    <header class="section-header"><div><h2>{{ t('adminUsage.title') }}</h2><p>{{ t('adminUsage.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="saving" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-alert theme="info" :message="t('adminUsage.scopeHint')" />
      <div class="filters"><label>{{ t('adminUsage.groupBy') }}<t-select v-model="groupBy" :options="groupOptions" :disabled="loading || saving" /></label><label>{{ t('adminUsage.start') }}<input v-model="start" type="date" :disabled="loading || saving" /></label><label>{{ t('adminUsage.end') }}<input v-model="end" type="date" :disabled="loading || saving" /></label><t-button theme="primary" :disabled="!validDates || loading || saving" @click="load">{{ t('adminUsage.query') }}</t-button></div>
      <t-alert v-if="!validDates" theme="warning" :message="t('adminUsage.invalidDates')" />
      <t-loading :loading="loading"><div v-if="ready" class="summary"><article><span>{{ t('adminUsage.totalRuns') }}</span><strong>{{ totalRuns.toLocaleString() }}</strong></article><article><span>{{ t('adminUsage.inputTokens') }}</span><strong>{{ totalInput.toLocaleString() }}</strong></article><article><span>{{ t('adminUsage.outputTokens') }}</span><strong>{{ totalOutput.toLocaleString() }}</strong></article><article><span>{{ t('adminUsage.totalTokens') }}</span><strong>{{ (totalInput + totalOutput).toLocaleString() }}</strong></article></div>
        <div v-if="ready" class="table-wrap"><table><thead><tr><th>{{ t('adminUsage.group') }}</th><th>{{ t('adminUsage.runs') }}</th><th>{{ t('adminUsage.inputTokens') }}</th><th>{{ t('adminUsage.outputTokens') }}</th><th>{{ t('adminUsage.cacheRead') }}</th><th>{{ t('adminUsage.cacheCreate') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.key"><td>{{ rowKey(row.key) }}</td><td>{{ row.runs.toLocaleString() }}</td><td>{{ row.input_tokens.toLocaleString() }}</td><td>{{ row.output_tokens.toLocaleString() }}</td><td>{{ row.cache_read_tokens.toLocaleString() }}</td><td>{{ row.cache_creation_tokens.toLocaleString() }}</td></tr><tr v-if="!rows.length"><td colspan="6">{{ t('adminUsage.empty') }}</td></tr></tbody></table></div>
      </t-loading>
      <section class="limits"><h3>{{ t('adminUsage.limitsTitle') }}</h3><p>{{ t('adminUsage.limitsHint') }}</p><div class="limit-form"><label>{{ t('adminUsage.scope') }}<t-select v-model="scopeChoice" :options="scopeOptions" :disabled="saving || loading || !scopeOptions.length" /></label><label>{{ t('adminUsage.monthlyTokens') }}<t-input-number v-model="limitValue" :min="1" :decimal-places="0" :disabled="saving || loading" /></label><t-button theme="primary" :loading="saving" :disabled="!ready || loading || saving || !limitValue || !Number.isSafeInteger(limitValue)" @click="addLimit">{{ t('adminUsage.save') }}</t-button></div>
        <div class="table-wrap"><table><thead><tr><th>{{ t('adminUsage.scope') }}</th><th>{{ t('adminUsage.monthlyTokens') }}</th><th>{{ t('adminUsage.usedThisMonth') }}</th><th>{{ t('adminUsage.actions') }}</th></tr></thead><tbody><tr v-for="row in limits" :key="row.id"><td>{{ labelForLimit(row) }}</td><td>{{ row.monthly_tokens.toLocaleString() }}</td><td>{{ row.used_this_month.toLocaleString() }}</td><td><t-button variant="text" theme="danger" :disabled="saving" @click="removeLimit(row)">{{ t('adminUsage.remove') }}</t-button></td></tr><tr v-if="ready && !limits.length"><td colspan="4">{{ t('adminUsage.noLimits') }}</td></tr></tbody></table></div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.usage-page { min-width: 0; }
.filters, .limit-form { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin: 18px 0; }
label { display: grid; gap: 6px; min-width: 150px; color: var(--td-text-color-secondary); }
input { font: inherit; color: var(--td-text-color-primary); background: var(--td-bg-color-container); border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-xs); padding: 6px 10px; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 18px 0; }
.summary article { display: grid; gap: 8px; padding: 16px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); }
.summary span, .limits p { color: var(--td-text-color-secondary); }
.summary strong { font-size: var(--app-text-xl); }
.table-wrap { overflow-x: auto; max-width: 100%; margin: 12px 0 24px; }
table { width: 100%; min-width: 700px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
.limits { margin-top: 32px; }
.limits h3 { margin-bottom: 8px; }
@media (max-width: 600px) { .filters, .limit-form { align-items: stretch; flex-direction: column; } label { width: 100%; } }
</style>
