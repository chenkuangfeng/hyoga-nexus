<script setup lang="ts">
/** 当前企业成员身份及本人退出操作，使用有效企业而非账号默认企业；不承载企业治理。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getEnterpriseInfo, type EnterpriseInfo } from '@nexus-web/core/api/enterprise-info'
import { leaveTenant } from '@nexus-web/core/api/tenant/members'
import { useAssistantDataChange } from '@nexus-web/core/utils/assistantDataChange'
import SettingsRow from '@nexus-web/core/components/SettingsRow.vue'
const auth = useAuthStore(), router = useRouter(), { t } = useI18n()
const info = ref<EnterpriseInfo | null>(null), loading = ref(false), busy = ref(false), visible = ref(false), error = ref('')
let epoch = 0
const owner = computed(() => info.value?.role === 'owner' || auth.currentTenantRole === 'owner')
const canLeave = computed(() => !!info.value && info.value.id === String(auth.effectiveTenantId) && ['admin','contributor','viewer'].includes(info.value.role) && !owner.value && !loading.value && !busy.value)
function message(reason: unknown) { return reason && typeof reason === 'object' && 'message' in reason && typeof reason.message === 'string' && reason.message !== 'admin_response_invalid' ? reason.message : t('adminConsole.failed') }
async function load() {
  const current = ++epoch
  info.value = null; visible.value = false; error.value = ''; loading.value = false; busy.value = false
  if (!auth.user?.id || !auth.effectiveTenantId) return
  const tenant = String(auth.effectiveTenantId)
  loading.value = true
  try { const row = await getEnterpriseInfo(tenant); if (current === epoch) info.value = row }
  catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) loading.value = false }
}
function openLeave() { if (canLeave.value) { error.value = ''; visible.value = true } }
async function leave() {
  if (!visible.value || !canLeave.value) return
  const current = epoch, tenant = String(auth.effectiveTenantId)
  busy.value = true; error.value = ''
  try {
    const result = await leaveTenant(tenant)
    if (current !== epoch) return
    if (!result.success) { error.value = result.message || t('adminConsole.failed'); return }
    visible.value = false
    auth.logout()
    await router.replace('/login')
  } catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) busy.value = false }
}
watch([() => auth.effectiveTenantId, () => auth.user?.id, () => auth.currentTenantRole], () => { void load() }, { immediate: true, flush: 'sync' })
useAssistantDataChange(() => { if (!busy.value) void load() }, { areas: ['workspace'] })
onBeforeUnmount(() => { epoch++; info.value = null; visible.value = false })
</script>
<template>
  <section class="enterprise-membership">
    <header><h3>{{ t('enterpriseMembership.title') }}</h3><t-button variant="text" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="error" theme="error" :message="error" />
    <t-loading :loading="loading"><template v-if="info">
      <SettingsRow :label="t('tenant.details.idLabel')"><span>{{ info.id }}</span></SettingsRow>
      <SettingsRow :label="t('enterpriseMembership.enterprise')"><span>{{ info.name }}</span></SettingsRow>
      <SettingsRow :label="t('tenant.details.descriptionLabel')"><span>{{ info.description || t('tenant.details.descriptionEmptyPlaceholder') }}</span></SettingsRow>
      <SettingsRow :label="t('enterpriseMembership.role')"><span>{{ t(`tenantMember.role.${info.role}`) }}</span></SettingsRow>
      <SettingsRow :label="t('tenant.details.statusLabel')"><span>{{ t(['active','inactive','suspended'].includes(info.status) ? `tenant.status${info.status[0].toUpperCase()}${info.status.slice(1)}` : 'tenant.statusUnknown') }}</span></SettingsRow>
      <SettingsRow :label="t('tenant.details.createdAtLabel')"><time>{{ info.created_at }}</time></SettingsRow>
      <p class="membership-hint">{{ t(owner ? 'enterpriseMembership.ownerHint' : 'enterpriseMembership.leaveHint') }}</p>
      <t-button theme="danger" variant="outline" :disabled="!canLeave" @click="openLeave">{{ t('enterpriseMembership.leave') }}</t-button>
    </template></t-loading>
    <t-dialog :visible="visible" :header="t('enterpriseMembership.confirmTitle')" :confirm-btn="{ content: t('enterpriseMembership.leave'), theme: 'danger', loading: busy, disabled: busy }" :cancel-btn="{ content: t('common.cancel'), disabled: busy }" :close-btn="!busy" :close-on-overlay-click="!busy" :close-on-esc-keydown="!busy" @close="() => { if (!busy) visible = false }" @confirm="leave">
      <p>{{ t('enterpriseMembership.confirmBody', { name: info?.name || '' }) }}</p><t-alert v-if="error" theme="error" :message="error" />
    </t-dialog>
  </section>
</template>
<style scoped>
.enterprise-membership { margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--td-component-stroke); }
header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
h3 { margin: 0; font-size: var(--app-text-xl); }
.membership-hint { color: var(--td-text-color-secondary); line-height: 1.6; margin: 24px 0 16px; }
</style>
