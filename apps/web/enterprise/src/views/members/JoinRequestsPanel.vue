<script setup lang="ts">
/** 当前企业的加入申请审批；部门加载失败不阻塞拒绝，旧作用域的请求和表单不能生效。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { approveEnterpriseApplication, listEnterpriseApplications, rejectEnterpriseApplication, type EnterpriseApplication, type InviteRole } from '@nexus-web/core/api/enterprise-members'
import { listPolicyDepartments, type DepartmentChoice } from '@nexus-web/core/api/enterprise-admin'
import { useEnterpriseContext } from '../../stores/context'
const props = withDefaults(defineProps<{ refreshKey?: number }>(), { refreshKey: 0 })
const emit = defineEmits<{ approved: []; busy: [value: boolean] }>()
const { t, locale } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const applications = ref<EnterpriseApplication[]>([]), departments = ref<DepartmentChoice[]>([])
const loading = ref(false), busy = ref(false), ready = ref(false), departmentsReady = ref(false)
const error = ref(''), departmentError = ref(''), success = ref(''), search = ref(''), page = ref(1)
const mode = ref<'' | 'approve' | 'reject'>(''), target = ref<EnterpriseApplication | null>(null)
const form = reactive<{ unit_id: string; role: InviteRole; reason: string }>({ unit_id: '', role: 'contributor', reason: '' })
const pageSize = 20
let epoch = 0
const canManage = computed(() => context.can('members:manage'))
const hasOrganization = computed(() => context.can('org:manage'))
const departmentHint = computed(() => departmentError.value ? t('adminApplications.departmentFailed') : t(hasOrganization.value ? 'adminApplications.noDepartments' : 'adminApplications.departmentPermission'))
const canApprove = computed(() => canManage.value && departmentsReady.value && departments.value.some(row => row.status === 'active'))
const filtered = computed(() => { const query = search.value.trim().toLowerCase(); return applications.value.filter(row => [row.display_name, row.email, row.message].some(value => (value || '').toLowerCase().includes(query))) })
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const roles = computed(() => ['admin', 'contributor', 'viewer'].map(value => ({ value, label: t(`tenantMember.role.${value}`) })))
const departmentOptions = computed(() => {
  const byId = new Map(departments.value.map(row => [row.id, row]))
  return departments.value.map(row => {
    const names = [row.name], seen = new Set([row.id]); let parent = row.parent_id
    while (parent && !seen.has(parent)) { seen.add(parent); const item = byId.get(parent); if (!item) break; names.unshift(item.name); parent = item.parent_id }
    return { value: row.id, label: names.join(' / '), disabled: row.status !== 'active' }
  })
})
const columns = computed(() => [{ colKey: 'applicant', title: t('adminApplications.applicant'), minWidth: 220 }, { colKey: 'message', title: t('adminApplications.message'), minWidth: 240 }, { colKey: 'created_at', title: t('adminApplications.appliedAt'), width: 190 }, { colKey: 'actions', title: t('adminMembers.operations'), width: 180 }])
const validDepartment = computed(() => departments.value.some(row => row.id === form.unit_id && row.status === 'active'))
const reasonValid = computed(() => form.reason.trim().length >= 1 && form.reason.trim().length <= 500)
const rules = computed(() => mode.value === 'approve' ? { unit_id: [{ required: true, message: t('adminApplications.departmentRequired'), type: 'error' }] } : { reason: [{ required: true, message: t('adminApplications.reasonRequired'), type: 'error' }] })
function message(reason: unknown): string { return reason instanceof Error && !['members_response_invalid', 'admin_response_invalid'].includes(reason.message) ? reason.message : t('adminConsole.failed') }
function name(row: EnterpriseApplication): string { return row.display_name || row.email || t('adminMembers.unnamedMember') }
function date(value: string): string { const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString(locale.value) }
function clearDialog() { mode.value = ''; target.value = null; Object.assign(form, { unit_id: '', role: 'contributor', reason: '' }) }
function closeDialog() { if (!busy.value) clearDialog() }
function invalidate() { epoch++; clearDialog(); applications.value = []; departments.value = []; ready.value = false; departmentsReady.value = false; loading.value = false; busy.value = false; error.value = ''; departmentError.value = ''; success.value = '' }
async function load() {
  invalidate()
  if (!canManage.value || !auth.effectiveTenantId) return
  const current = epoch, tenant = String(auth.effectiveTenantId)
  loading.value = true
  const result = await Promise.allSettled([listEnterpriseApplications(tenant), hasOrganization.value ? listPolicyDepartments(tenant) : Promise.resolve(null)])
  if (current !== epoch) return
  if (result[0].status === 'fulfilled') { applications.value = result[0].value; ready.value = true } else error.value = message(result[0].reason)
  if (result[1].status === 'fulfilled' && result[1].value !== null) { departments.value = result[1].value; departmentsReady.value = true }
  else if (result[1].status === 'rejected') departmentError.value = message(result[1].reason)
  loading.value = false
}
function open(next: 'approve' | 'reject', row: EnterpriseApplication) {
  if (!canManage.value || !ready.value || busy.value || loading.value || (next === 'approve' && !canApprove.value)) return
  const current = applications.value.find(item => item.id === row.id)
  if (!current) return
  clearDialog(); target.value = current; mode.value = next; form.role = current.role
  if (current.unit_id && departments.value.some(item => item.id === current.unit_id && item.status === 'active')) form.unit_id = current.unit_id
  error.value = ''; success.value = ''
}
async function submit({ validateResult }: { validateResult: unknown }) {
  const row = target.value, action = mode.value
  if (validateResult !== true || !canManage.value || !ready.value || busy.value || loading.value || !row || !applications.value.some(item => item.id === row.id) || !action) return
  if (action === 'approve' && (!canApprove.value || !validDepartment.value || !['admin', 'contributor', 'viewer'].includes(form.role))) return
  if (action === 'reject' && !reasonValid.value) return
  const current = epoch, tenant = String(auth.effectiveTenantId)
  busy.value = true; error.value = ''; success.value = ''
  try {
    if (action === 'approve') await approveEnterpriseApplication(tenant, row.id, { unit_id: form.unit_id, role: form.role }, row.user_id)
    else await rejectEnterpriseApplication(tenant, row.id, form.reason.trim())
    if (current !== epoch) return
    applications.value = applications.value.filter(item => item.id !== row.id)
    clearDialog(); success.value = t(action === 'approve' ? 'adminApplications.approved' : 'adminApplications.rejected')
    if (action === 'approve') emit('approved')
  } catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) busy.value = false }
}
watch(busy, value => emit('busy', value), { flush: 'sync' })
watch(search, () => { page.value = 1 })
watch(() => filtered.value.length, count => { page.value = Math.min(page.value, Math.max(1, Math.ceil(count / pageSize))) })
watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.revision, canManage, hasOrganization, () => props.refreshKey], () => { search.value = ''; page.value = 1; void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { invalidate(); emit('busy', false) })
</script>
<template>
  <section class="join-requests">
    <div class="request-toolbar"><t-input v-model="search" :placeholder="t('adminApplications.search')" :aria-label="t('adminApplications.search')" clearable /><t-button variant="outline" :disabled="busy" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button></div>
    <t-alert v-if="!canManage" theme="warning" :message="t('adminMembers.denied')" />
    <template v-else>
      <p>{{ t('adminApplications.description') }}</p>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-alert v-if="success" theme="success" :message="success" />
      <t-alert v-if="!loading && !canApprove" theme="info" :message="departmentHint"><template v-if="hasOrganization" #operation><RouterLink to="/organization">{{ t('adminOrganization.open') }}</RouterLink></template></t-alert>
      <div class="data-table-shell"><t-table v-if="ready || loading" row-key="id" :data="rows" :columns="columns" :loading="loading" :empty="t(search ? 'adminMembers.noMatch' : 'adminApplications.empty')">
        <template #applicant="{ row }"><strong>{{ name(row) }}</strong><p>{{ row.email || '—' }}</p></template>
        <template #message="{ row }"><p class="request-message">{{ row.message || '—' }}</p></template>
        <template #created_at="{ row }">{{ date(row.created_at) }}</template>
        <template #actions="{ row }"><div class="request-actions"><t-button variant="text" :disabled="busy || loading || !canApprove" @click="open('approve', row)">{{ t('adminApplications.approve') }}</t-button><t-button variant="text" theme="danger" :disabled="busy || loading || !ready" @click="open('reject', row)">{{ t('adminApplications.reject') }}</t-button></div></template>
      </t-table></div>
      <t-pagination v-if="filtered.length > pageSize" v-model="page" :page-size="pageSize" :total="filtered.length" :show-page-size="false" />
    </template>
    <t-dialog :visible="!!mode" :header="t(mode === 'approve' ? 'adminApplications.approveTitle' : 'adminApplications.rejectTitle')" :footer="false" :close-btn="!busy" :close-on-overlay-click="!busy" :close-on-esc-keydown="!busy" @close="closeDialog">
      <template v-if="target">
        <p>{{ t('adminApplications.target', { name: name(target) }) }}</p><p class="request-message">{{ target.message || '—' }}</p>
        <t-alert v-if="error" theme="error" :message="error" />
        <t-form :data="form" :rules="rules" layout="vertical" :disabled="busy" @submit="submit">
          <template v-if="mode === 'approve'">
            <p>{{ t('adminApplications.approveHint') }}</p>
            <t-form-item name="unit_id" :label="t('adminApplications.department')"><t-select v-model="form.unit_id" :options="departmentOptions" filterable /></t-form-item>
            <t-form-item :label="t('adminMembers.role')"><t-select v-model="form.role" :options="roles" /></t-form-item>
          </template>
          <template v-else>
            <t-alert theme="warning" :message="t('adminApplications.rejectHint')" />
            <t-form-item name="reason" :label="t('adminApplications.reason')" :help="t('adminApplications.reasonRequired')"><t-textarea v-model="form.reason" :maxlength="500" :autosize="{ minRows: 3, maxRows: 6 }" /></t-form-item>
          </template>
          <div class="request-actions"><t-button type="submit" :theme="mode === 'approve' ? 'primary' : 'danger'" :loading="busy" :disabled="mode === 'approve' ? !canApprove || !validDepartment : !reasonValid">{{ t(mode === 'approve' ? 'adminApplications.confirmApprove' : 'adminApplications.confirmReject') }}</t-button><t-button variant="outline" :disabled="busy" @click="closeDialog">{{ t('common.cancel') }}</t-button></div>
        </t-form>
      </template>
    </t-dialog>
  </section>
</template>
<style scoped>
.join-requests { display: grid; gap: 16px; padding-top: 0; }
.request-toolbar,.request-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.request-toolbar :deep(.t-input__wrap) { max-width: 320px; }
p { color: var(--td-text-color-secondary); font-size: var(--app-text-md); line-height: 1.5; margin: 4px 0; }
.request-message { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
