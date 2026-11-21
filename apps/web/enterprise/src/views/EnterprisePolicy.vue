<script setup lang="ts">
/** 企业策略编辑。部门列表不可读时保留原范围；保存前确认，旧身份的请求与确认均失效。 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getEnterprisePolicy, listPolicyDepartments, policyChanges, updateEnterprisePolicy, type DepartmentChoice, type EnterprisePolicy } from '@nexus-web/core/api/enterprise-admin'
import { useEnterpriseContext } from '../stores/context'
import SettingsRow from '@nexus-web/core/components/SettingsRow.vue'
const { t } = useI18n()
const auth = useAuthStore(), context = useEnterpriseContext()
const form = reactive<EnterprisePolicy>({ self_build_agents: 'none', self_build_org_unit_ids: [], personal_models: false, external_sharing: false, personal_wecom_channels: 'disabled', personal_external_channels: false, retention_days: null })
const snapshot = ref<EnterprisePolicy | null>(null), departments = ref<DepartmentChoice[]>([])
const loading = ref(false), busy = ref(false), error = ref(''), departmentError = ref(false), departmentsReady = ref(false), saved = ref(false)
const autoPurge = ref(false), days = ref<number | undefined>(90)
let epoch = 0
let confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const canWrite = computed(() => context.can('policy:manage'))
const canChooseDepartments = computed(() => canWrite.value && context.can('org:manage') && departmentsReady.value)
const changes = computed(() => snapshot.value ? policyChanges(snapshot.value, form) : {})
const dirty = computed(() => Object.keys(changes.value).length > 0)
const validDays = computed(() => !autoPurge.value || (typeof days.value === 'number' && Number.isInteger(days.value) && days.value >= 1 && days.value <= 3650))
const modeOptions = computed(() => ['all', 'org_units', 'none'].map(value => ({ value, label: t(`adminConsole.selfBuild.${value}`), disabled: value === 'org_units' && !canChooseDepartments.value })))
const channelOptions = computed(() => ['review', 'open', 'disabled'].map(value => ({ value, label: t(`adminConsole.wecomModes.${value}`) })))
const departmentOptions = computed(() => departments.value.map(row => ({ value: row.id, label: row.name, disabled: row.status !== 'active' })))
function clone(row: EnterprisePolicy): EnterprisePolicy { return { ...row, self_build_org_unit_ids: [...row.self_build_org_unit_ids] } }
function accept(row: EnterprisePolicy) { snapshot.value = clone(row); Object.assign(form, clone(row)); autoPurge.value = row.retention_days !== null; days.value = row.retention_days ?? 90 }
function message(reason: unknown) { return reason instanceof Error && reason.message !== 'admin_response_invalid' ? reason.message : t('adminConsole.failed') }
async function load() {
  const current = ++epoch
  confirmation?.hide(); confirmation = undefined
  snapshot.value = null; departments.value = []; departmentsReady.value = false; departmentError.value = false; busy.value = false; error.value = ''; saved.value = false; loading.value = false
  if (!context.ready || !auth.effectiveTenantId) return
  const tenant = String(auth.effectiveTenantId)
  loading.value = true
  try {
    const row = await getEnterprisePolicy(tenant)
    if (current !== epoch) return
    accept(row)
    if (context.can('org:manage')) {
      try { const rows = await listPolicyDepartments(tenant); if (current === epoch) { departments.value = rows; departmentsReady.value = true } }
      catch { if (current === epoch) departmentError.value = true }
    }
  } catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) loading.value = false }
}
function reset() { if (snapshot.value && !busy.value) { accept(snapshot.value); error.value = ''; saved.value = false } }
function submit({ validateResult }: { validateResult: unknown }) {
  if (validateResult !== true || !canWrite.value || !snapshot.value || busy.value || loading.value || !dirty.value || !validDays.value || confirmation) return
  const current = epoch, tenant = String(auth.effectiveTenantId), input = { ...changes.value }
  const dialog = DialogPlugin.confirm({
    header: t('adminConsole.confirmTitle'), body: t('adminConsole.confirmHint'),
    onConfirm: async () => {
      dialog.hide(); if (confirmation === dialog) confirmation = undefined
      if (current !== epoch || !canWrite.value || busy.value) return
      busy.value = true; error.value = ''; saved.value = false
      try { const row = await updateEnterprisePolicy(tenant, input); if (current === epoch) { accept(row); saved.value = true } }
      catch (reason) { if (current === epoch) error.value = message(reason) }
      finally { if (current === epoch) busy.value = false }
    },
    onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
watch([autoPurge, days], () => { form.retention_days = autoPurge.value ? days.value ?? null : null }, { flush: 'sync' })
watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.ready, () => context.revision], () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { epoch++; confirmation?.hide(); confirmation = undefined; snapshot.value = null })
</script>
<template>
  <section class="policy-page">
    <header class="section-header"><div><h2>{{ t('adminConsole.policy') }}</h2><p>{{ t('adminConsole.policyHint') }}</p></div><t-button class="settings-list-button" theme="default" variant="outline" :disabled="busy" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="error" theme="error" :message="error" />
    <t-alert v-if="saved" theme="success" :message="t('adminConsole.saved')" />
    <t-alert v-if="snapshot && !canWrite" theme="info" :message="t('adminConsole.readOnly')" />
    <t-loading :loading="loading">
      <t-form v-if="snapshot" :data="form" layout="vertical" :disabled="!canWrite || busy || loading" @submit="submit">
        <div class="policy-group">
          <h2>{{ t('adminConsole.resources') }}</h2>
          <SettingsRow :label="t('adminConsole.buildScope')" :description="t('adminConsole.buildHint')"><t-select :aria-label="t('adminConsole.buildScope')" v-model="form.self_build_agents" :options="modeOptions" /></SettingsRow>
          <template v-if="form.self_build_agents === 'org_units'">
            <SettingsRow v-if="canChooseDepartments" :label="t('adminConsole.departments')"><t-select :aria-label="t('adminConsole.departments')" v-model="form.self_build_org_unit_ids" :options="departmentOptions" multiple filterable /></SettingsRow>
            <p v-else>{{ t('adminConsole.departmentCount', { count: form.self_build_org_unit_ids.length }) }}</p>
            <t-alert v-if="!canChooseDepartments" :theme="departmentError ? 'warning' : 'info'" :message="t('adminConsole.departmentUnavailable')" />
          </template>
          <SettingsRow :label="t('adminConsole.personalModels')"><t-switch v-model="form.personal_models" :aria-label="t('adminConsole.personalModels')" /></SettingsRow>
          <SettingsRow :label="t('adminConsole.externalSharing')"><t-switch v-model="form.external_sharing" :aria-label="t('adminConsole.externalSharing')" /></SettingsRow>
        </div>
        <div class="policy-group">
          <h2>{{ t('adminConsole.channels') }}</h2>
          <SettingsRow :label="t('adminConsole.personalWecom')" :description="t('adminConsole.channelHint')"><t-select :aria-label="t('adminConsole.personalWecom')" v-model="form.personal_wecom_channels" :options="channelOptions" /></SettingsRow>
          <SettingsRow :label="t('adminConsole.personalExternal')"><t-switch v-model="form.personal_external_channels" :aria-label="t('adminConsole.personalExternal')" /></SettingsRow>
        </div>
        <div class="policy-group">
          <h2>{{ t('adminConsole.retention') }}</h2>
          <SettingsRow :label="t('adminConsole.autoPurge')"><t-switch v-model="autoPurge" :aria-label="t('adminConsole.autoPurge')" /></SettingsRow>
          <SettingsRow v-if="autoPurge" :label="t('adminConsole.retentionDays')"><t-form-item :status="validDays ? undefined : 'error'" :help="validDays ? undefined : t('adminConsole.daysInvalid')"><t-input-number :aria-label="t('adminConsole.retentionDays')" v-model="days" :min="1" :max="3650" :decimal-places="0" /></t-form-item></SettingsRow>
          <t-alert theme="warning" :message="t('adminConsole.retentionHint')" />
        </div>
        <div class="policy-actions"><t-button v-if="canWrite" type="submit" theme="primary" :loading="busy" :disabled="!dirty || loading || !validDays">{{ t('common.save') }}</t-button><t-button variant="outline" :disabled="!dirty || busy || loading" @click="reset">{{ t('adminConsole.reset') }}</t-button></div>
      </t-form>
    </t-loading>
  </section>
</template>
<style scoped>
.policy-page { width: 100%; }
.policy-group { padding: 8px 0 24px; border-bottom: 1px solid var(--td-component-stroke); }
.policy-group h2 { margin: 20px 0 0; font-size: var(--app-text-xl); font-weight: 600; }
.policy-group p { color: var(--td-text-color-secondary); font-size: var(--app-text-md); line-height: 1.5; }
.policy-group :deep(.setting-control .t-select__wrap) { width: 280px; max-width: 100%; }
.policy-group :deep(.t-form__item) { margin: 20px 0; }
.policy-actions { display: flex; gap: 12px; padding: 24px 0; }
</style>
