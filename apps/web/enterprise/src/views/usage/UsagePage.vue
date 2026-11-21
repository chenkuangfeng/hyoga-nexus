<script setup lang="ts">
/** 企业 Token 用量与月度上限；金额并非现有服务端统计的一部分。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getEnterpriseUsage, listEnterpriseUsageLimits, saveEnterpriseUsageLimit, type EnterpriseUsageLimit, type EnterpriseUsageRow, type UsageGroup } from '@nexus-web/core/api/enterprise-usage'
import { listEnterpriseMembers, type EnterpriseMember } from '@nexus-web/core/api/enterprise-members'
import { listOrganizationUnits, type OrganizationNode } from '@nexus-web/core/api/enterprise-organizations'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.can('models:manage'))
const canReadMembers = computed(() => context.can('members:manage'))
const canReadOrganization = computed(() => context.can('org:manage'))
// 目录授权也是作用域的一部分：撤销目录权限时立即作废已打开的范围确认。
const scopeKey = computed(() => JSON.stringify([tenant.value, auth.user?.id || '', context.revision,
  canManage.value, canReadMembers.value, canReadOrganization.value]))
function today() { const date = new Date(); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}` }
function monthStart() { return `${today().slice(0, 7)}-01` }
const start = ref(monthStart()), end = ref(today()), groupBy = ref<UsageGroup>('day')
const reportGroup = ref<UsageGroup>('day')
const rows = ref<EnterpriseUsageRow[]>([]), limits = ref<EnterpriseUsageLimit[]>([])
const members = ref<EnterpriseMember[]>([]), units = ref<OrganizationNode[]>([])
const loading = ref(false), saving = ref(false), ready = ref(false), error = ref('')
const directoryErrors = ref<string[]>([]), limitValue = ref<number | undefined>(), scopeChoice = ref('tenant')
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const groupOptions = computed(() => [{ value: 'day', label: t('adminUsage.byDay') },
  ...(canReadMembers.value ? [{ value: 'user', label: t('adminUsage.byMember') }] : []),
  ...(canReadOrganization.value ? [{ value: 'org_unit', label: t('adminUsage.byDepartment') }] : [])])
// 范围 ID 来自已加载目录，不从任意输入拆字符串或推断授权。
const scopeOptions = computed<Array<{ value: string; label: string; kind: EnterpriseUsageLimit['scope_kind']; id: string | null }>>(() => [
  { value: 'tenant', label: t('adminUsage.enterprise'), kind: 'tenant', id: null },
  ...(canReadOrganization.value ? units.value.map(row => ({ value: `org_unit:${row.id}`, label: `${t('adminUsage.department')}: ${row.name}`, kind: 'org_unit' as const, id: row.id })) : []),
  ...(canReadMembers.value ? members.value.map(row => ({ value: `user:${row.user_id}`, label: `${t('adminUsage.member')}: ${row.display_name || row.username || row.email || row.user_id}`, kind: 'user' as const, id: row.user_id })) : []),
])
const memberNames = computed(() => new Map(members.value.map(row => [row.user_id, row.display_name || row.username || row.email || row.user_id])))
const unitNames = computed(() => new Map(units.value.map(row => [row.id, row.name])))
const totalInput = computed(() => rows.value.reduce((sum, row) => sum + row.input_tokens, 0))
const totalOutput = computed(() => rows.value.reduce((sum, row) => sum + row.output_tokens, 0))
const totalRuns = computed(() => rows.value.reduce((sum, row) => sum + row.runs, 0))
function validDate(value: string) { return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value }
const validDates = computed(() => validDate(start.value) && validDate(end.value) && start.value <= end.value)
function invalidate() {
  epoch++; confirmation?.hide(); confirmation = undefined
  rows.value = []; limits.value = []; members.value = []; units.value = []; directoryErrors.value = []
  ready.value = false; loading.value = false; saving.value = false; error.value = ''
  limitValue.value = undefined; scopeChoice.value = 'tenant'; reportGroup.value = 'day'
}
function isCurrent(request: number, scope: string) { return request === epoch && scope === scopeKey.value && canManage.value }
function labelForLimit(row: EnterpriseUsageLimit) { return row.scope_kind === 'tenant' ? t('adminUsage.enterprise') : row.scope_kind === 'user' ? memberNames.value.get(row.scope_id) || row.scope_id : unitNames.value.get(row.scope_id) || row.scope_id }
async function load() {
  invalidate()
  if (!canManage.value || !tenant.value) return
  if (!groupOptions.value.some(option => option.value === groupBy.value)) groupBy.value = 'day'
  if (!validDates.value) { error.value = t('adminUsage.invalidDates'); return }
  const request = epoch, scope = scopeKey.value, requestedTenant = tenant.value, queryGroup = groupBy.value
  loading.value = true
  try {
    const [report, savedLimits] = await Promise.all([getEnterpriseUsage(requestedTenant, queryGroup, start.value, end.value), listEnterpriseUsageLimits(requestedTenant)])
    if (!isCurrent(request, scope)) return
    rows.value = report; limits.value = savedLimits; reportGroup.value = queryGroup; ready.value = true
    // 目录失败不影响企业报表；单独反馈不可用目录，避免把故障伪装成空目录。
    const optional: Promise<void>[] = []
    if (canReadMembers.value) optional.push(listEnterpriseMembers(requestedTenant)
      .then(value => { if (isCurrent(request, scope)) members.value = value })
      .catch(() => { if (isCurrent(request, scope)) directoryErrors.value.push(t('adminUsage.directoryFailed', { directory: t('adminUsage.member') })) }))
    if (canReadOrganization.value) optional.push(listOrganizationUnits(requestedTenant)
      .then(value => { if (isCurrent(request, scope)) units.value = value })
      .catch(() => { if (isCurrent(request, scope)) directoryErrors.value.push(t('adminUsage.directoryFailed', { directory: t('adminUsage.department') })) }))
    await Promise.all(optional)
  } catch { if (isCurrent(request, scope)) error.value = t('adminUsage.loadFailed') }
  finally { if (isCurrent(request, scope)) loading.value = false }
}
watch(scopeKey, () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(invalidate)
/** 筛选草稿不会改变旧报表行的含义；只使用实际返回数据的分组快照。 */
function rowKey(key: string) { return reportGroup.value === 'day' ? key : reportGroup.value === 'user' ? memberNames.value.get(key) || key : unitNames.value.get(key) || key }
function addLimit() {
  if (!canManage.value || saving.value || loading.value || !ready.value || confirmation
      || !Number.isSafeInteger(limitValue.value) || !limitValue.value || limitValue.value < 1) return
  const target = scopeOptions.value.find(item => item.value === scopeChoice.value)
  if (!target) return
  const request = epoch, scope = scopeKey.value, requestedTenant = tenant.value
  const kind = target.kind, id = target.id, tokens = limitValue.value
  const dialog = DialogPlugin.confirm({ header: t('adminUsage.saveTitle'), body: t('adminUsage.saveConfirm', { scope: target.label, tokens }),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (!isCurrent(request, scope) || saving.value) return
      saving.value = true; error.value = ''
      try {
        // 提交确认框展示的范围和数值，不能读取确认期间变动的表单草稿。
        await saveEnterpriseUsageLimit(requestedTenant, kind, id, tokens)
        if (!isCurrent(request, scope)) return
        MessagePlugin.success(t('adminUsage.saved')); await load()
      } catch { if (isCurrent(request, scope)) error.value = t('adminUsage.saveFailed') }
      finally { if (isCurrent(request, scope)) saving.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
function removeLimit(row: EnterpriseUsageLimit) {
  if (!canManage.value || saving.value || loading.value || !ready.value || confirmation || !limits.value.includes(row)) return
  const request = epoch, scope = scopeKey.value, requestedTenant = tenant.value
  const kind = row.scope_kind, id = kind === 'tenant' ? null : row.scope_id
  const dialog = DialogPlugin.confirm({ header: t('adminUsage.removeTitle'), body: t('adminUsage.removeConfirm', { scope: labelForLimit(row) }), theme: 'warning', onConfirm: async () => {
    if (confirmation !== dialog) return
    dialog.hide(); confirmation = undefined
    if (!isCurrent(request, scope) || saving.value) return
    saving.value = true; error.value = ''
    try {
      await saveEnterpriseUsageLimit(requestedTenant, kind, id, null)
      if (!isCurrent(request, scope)) return
      MessagePlugin.success(t('adminUsage.removed')); await load()
    } catch { if (isCurrent(request, scope)) error.value = t('adminUsage.removeFailed') }
    finally { if (isCurrent(request, scope)) saving.value = false }
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
      <t-alert v-for="message in directoryErrors" :key="message" theme="warning" :message="message" />
      <div class="filters"><label>{{ t('adminUsage.groupBy') }}<t-select v-model="groupBy" :options="groupOptions" :disabled="loading || saving" /></label><label>{{ t('adminUsage.start') }}<input v-model="start" type="date" :disabled="loading || saving" /></label><label>{{ t('adminUsage.end') }}<input v-model="end" type="date" :disabled="loading || saving" /></label><t-button theme="primary" :disabled="!validDates || loading || saving" @click="load">{{ t('adminUsage.query') }}</t-button></div>
      <t-alert v-if="!validDates" theme="warning" :message="t('adminUsage.invalidDates')" />
      <t-loading :loading="loading"><div v-if="ready" class="summary"><article><span>{{ t('adminUsage.totalRuns') }}</span><strong>{{ totalRuns.toLocaleString() }}</strong></article><article><span>{{ t('adminUsage.inputTokens') }}</span><strong>{{ totalInput.toLocaleString() }}</strong></article><article><span>{{ t('adminUsage.outputTokens') }}</span><strong>{{ totalOutput.toLocaleString() }}</strong></article><article><span>{{ t('adminUsage.totalTokens') }}</span><strong>{{ (totalInput + totalOutput).toLocaleString() }}</strong></article></div>
        <div v-if="ready" class="table-wrap"><table><thead><tr><th>{{ t('adminUsage.group') }}</th><th>{{ t('adminUsage.runs') }}</th><th>{{ t('adminUsage.inputTokens') }}</th><th>{{ t('adminUsage.outputTokens') }}</th><th>{{ t('adminUsage.cacheRead') }}</th><th>{{ t('adminUsage.cacheCreate') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.key"><td>{{ rowKey(row.key) }}</td><td>{{ row.runs.toLocaleString() }}</td><td>{{ row.input_tokens.toLocaleString() }}</td><td>{{ row.output_tokens.toLocaleString() }}</td><td>{{ row.cache_read_tokens.toLocaleString() }}</td><td>{{ row.cache_creation_tokens.toLocaleString() }}</td></tr><tr v-if="!rows.length"><td colspan="6">{{ t('adminUsage.empty') }}</td></tr></tbody></table></div>
      </t-loading>
      <section class="limits"><h3>{{ t('adminUsage.limitsTitle') }}</h3><p>{{ t('adminUsage.limitsHint') }}</p><div class="limit-form"><label>{{ t('adminUsage.scope') }}<t-select v-model="scopeChoice" :options="scopeOptions" :disabled="saving || loading || !scopeOptions.length" /></label><label>{{ t('adminUsage.monthlyTokens') }}<t-input-number v-model="limitValue" :min="1" :decimal-places="0" :disabled="saving || loading" /></label><t-button theme="primary" :loading="saving" :disabled="!ready || loading || saving || !limitValue || !Number.isSafeInteger(limitValue) || !scopeOptions.some(option => option.value === scopeChoice)" @click="addLimit">{{ t('adminUsage.save') }}</t-button></div>
        <div class="table-wrap"><table><thead><tr><th>{{ t('adminUsage.scope') }}</th><th>{{ t('adminUsage.monthlyTokens') }}</th><th>{{ t('adminUsage.usedThisMonth') }}</th><th>{{ t('adminUsage.actions') }}</th></tr></thead><tbody><tr v-for="row in limits" :key="row.id"><td>{{ labelForLimit(row) }}</td><td>{{ row.monthly_tokens.toLocaleString() }}</td><td>{{ row.used_this_month.toLocaleString() }}</td><td><t-button variant="text" theme="danger" :disabled="saving || loading || !ready" @click="removeLimit(row)">{{ t('adminUsage.remove') }}</t-button></td></tr><tr v-if="ready && !limits.length"><td colspan="4">{{ t('adminUsage.noLimits') }}</td></tr></tbody></table></div>
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
