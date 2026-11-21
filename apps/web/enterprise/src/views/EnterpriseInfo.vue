<script setup lang="ts">
/** 企业基本信息：owner 修改与归档；切换身份或权限代次时作废旧请求和确认。 */
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { getEnterpriseInfo, updateEnterpriseInfo, archiveEnterprise, type EnterpriseInfo } from '@nexus-web/core/api/enterprise-info'
import { copyToClipboard } from '@nexus-web/core/utils/clipboard'
import SettingsRow from '@nexus-web/core/components/SettingsRow.vue'
import { useEnterpriseContext } from '../stores/context'
const auth = useAuthStore(), context = useEnterpriseContext(), router = useRouter(), { t } = useI18n()
const snapshot = ref<EnterpriseInfo | null>(null)
const name = ref(''), description = ref(''), error = ref(''), saved = ref(false)
const copyBusy = ref(false), copyFeedback = ref(''), copyFailed = ref(false)
const loading = ref(false), busy = ref(false), deleteVisible = ref(false), confirmationName = ref('')
let epoch = 0, live = true
const codeAvailable = computed(() => !!snapshot.value?.code?.trim())
const allowed = computed(() => context.ready && auth.currentTenantRole === 'owner')
const canWrite = computed(() => allowed.value && snapshot.value?.role === 'owner')
const changes = computed(() => {
  const result: { name?: string; description?: string } = {}
  if (snapshot.value && name.value.trim() !== snapshot.value.name) result.name = name.value.trim()
  if (snapshot.value && description.value.trim() !== snapshot.value.description) result.description = description.value.trim()
  return result
})
const valid = computed(() => !!name.value.trim() && name.value.trim().length <= 160 && description.value.trim().length <= 500)
const dirty = computed(() => Object.keys(changes.value).length > 0)
function accept(row: EnterpriseInfo) { snapshot.value = row; name.value = row.name; description.value = row.description }
/** Copy the loaded code; discard feedback after account, enterprise or permission changes. */
async function copyCode() {
  const code = snapshot.value?.code
  if (!live || !allowed.value || !code?.trim() || copyBusy.value || loading.value || busy.value) return
  const current = epoch, tenant = String(auth.effectiveTenantId), user = auth.user?.id
  copyBusy.value = true; copyFeedback.value = ''
  try {
    const ok = await copyToClipboard(code)
    if (!live || current !== epoch || tenant !== String(auth.effectiveTenantId) || user !== auth.user?.id || !allowed.value) return
    copyFailed.value = !ok
    copyFeedback.value = t(ok ? 'adminEnterprise.codeCopied' : 'adminEnterprise.codeCopyFailed')
  } catch {
    if (live && current === epoch && allowed.value) { copyFailed.value = true; copyFeedback.value = t('adminEnterprise.codeCopyFailed') }
  } finally { if (live && current === epoch) copyBusy.value = false }
}
function failure(reason: unknown) {
  if (reason && typeof reason === 'object' && 'message' in reason && typeof reason.message === 'string' && reason.message !== 'admin_response_invalid') return reason.message
  return t('adminConsole.failed')
}
/** 重读时清空旧快照，读取失败不得保留可提交的旧表单。 */
async function load() {
  const current = ++epoch
  copyBusy.value = false; copyFeedback.value = ''; copyFailed.value = false
  snapshot.value = null; name.value = ''; description.value = ''; error.value = ''; saved.value = false
  deleteVisible.value = false; confirmationName.value = ''; busy.value = false; loading.value = false
  if (!allowed.value || !auth.effectiveTenantId) return
  const tenant = String(auth.effectiveTenantId)
  loading.value = true
  try { const row = await getEnterpriseInfo(tenant, true); if (current === epoch) accept(row) }
  catch (reason) { if (current === epoch) error.value = failure(reason) }
  finally { if (current === epoch) loading.value = false }
}
function reset() { if (snapshot.value && !busy.value) { accept(snapshot.value); error.value = ''; saved.value = false } }
async function save() {
  if (!canWrite.value || !valid.value || !dirty.value || busy.value || loading.value) return
  const current = epoch, tenant = String(auth.effectiveTenantId), input = { ...changes.value }
  busy.value = true; error.value = ''; saved.value = false
  try {
    const row = await updateEnterpriseInfo(tenant, input, true)
    if (current !== epoch) return
    accept(row); saved.value = true
    // 仅更新当前作用域的可读名称，避免侧栏继续显示旧名称。
    auth.setSelectedTenant(tenant, row.name)
    auth.setMemberships(auth.memberships.map(m => String(m.tenant_id) === tenant ? { ...m, tenant_name: row.name } : m))
  } catch (reason) { if (current === epoch) error.value = failure(reason) }
  finally { if (current === epoch) busy.value = false }
}
function openDelete() {
  if (!canWrite.value || busy.value || loading.value) return
  confirmationName.value = ''; deleteVisible.value = true
}
async function remove() {
  if (!canWrite.value || busy.value || !deleteVisible.value || confirmationName.value.trim() !== snapshot.value?.name) return
  const current = epoch, tenant = String(auth.effectiveTenantId)
  busy.value = true; error.value = ''
  try {
    await archiveEnterprise(tenant)
    if (current !== epoch) return
    // 删除成功后清除管理上下文与认证状态，在本应用重新登录选择剩余企业。
    // 不把成功后的身份刷新失败展示为“删除失败”，也不跨应用跳转。
    deleteVisible.value = false; context.invalidate(); auth.logout(); await router.replace('/login')
  } catch (reason) { if (current === epoch) error.value = failure(reason) }
  finally { if (current === epoch) busy.value = false }
}
watch([() => auth.effectiveTenantId, () => auth.user?.id, () => auth.currentTenantRole, () => context.ready, () => context.revision], () => { void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { live = false; epoch++; snapshot.value = null; deleteVisible.value = false })
</script>
<template>
  <section>
    <header class="section-header"><div><h2>{{ t('adminEnterprise.title') }}</h2><p>{{ t('adminEnterprise.description') }}</p></div><t-button class="settings-list-button" variant="outline" :disabled="busy" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!allowed" theme="info" :message="t('adminConsole.denied')" />
    <t-alert v-if="error" theme="error" :message="error" />
    <t-alert v-if="saved" theme="success" :message="t('adminEnterprise.saved')" />
    <t-loading :loading="loading">
      <template v-if="snapshot">
        <t-form :data="{ name, description }" :disabled="!canWrite || busy" @submit="save">
          <SettingsRow :label="t('tenant.details.nameLabel')" :description="t('tenant.details.nameDescription')"><t-input v-model="name" :aria-label="t('tenant.details.nameLabel')" :maxlength="160" /></SettingsRow>
          <SettingsRow :label="t('adminEnterprise.codeLabel')" :description="t('adminEnterprise.codeHint')"><div class="enterprise-code"><code v-if="codeAvailable">{{ snapshot.code }}</code><span v-else>{{ t('adminEnterprise.codeMissing') }}</span><t-button type="button" variant="text" :loading="copyBusy" :disabled="!codeAvailable || copyBusy || busy || loading" @click="copyCode">{{ t('adminEnterprise.copyCode') }}</t-button><span v-if="copyFeedback" role="status" :class="{ 'copy-error': copyFailed }">{{ copyFeedback }}</span></div></SettingsRow>
          <SettingsRow :label="t('tenant.details.descriptionLabel')" :description="t('tenant.details.descriptionDescription')"><t-textarea v-model="description" :aria-label="t('tenant.details.descriptionLabel')" :maxlength="500" :autosize="{ minRows: 2, maxRows: 6 }" /></SettingsRow>
          <SettingsRow :label="t('tenant.details.statusLabel')"><span>{{ t(['active', 'inactive', 'suspended'].includes(snapshot.status) ? `tenant.status${snapshot.status[0].toUpperCase()}${snapshot.status.slice(1)}` : 'tenant.statusUnknown') }}</span></SettingsRow>
          <SettingsRow :label="t('tenant.details.createdAtLabel')"><time>{{ snapshot.created_at }}</time></SettingsRow>
          <div class="info-actions"><t-button type="submit" theme="primary" :loading="busy" :disabled="!canWrite || !valid || !dirty">{{ t('common.save') }}</t-button><t-button variant="outline" :disabled="busy || !dirty" @click="reset">{{ t('adminConsole.reset') }}</t-button></div>
        </t-form>
        <SettingsRow v-if="canWrite" :label="t('tenant.deleteDangerZone.title')" :description="t('tenant.deleteDangerZone.desc')"><t-button theme="danger" variant="outline" :disabled="busy" @click="openDelete">{{ t('tenant.deleteDangerZone.button') }}</t-button></SettingsRow>
      </template>
    </t-loading>
    <t-dialog :visible="deleteVisible" :header="t('tenant.deleteDangerZone.confirmTitle')" :confirm-btn="{ content: t('tenant.deleteDangerZone.confirm'), theme: 'danger', loading: busy, disabled: busy || confirmationName.trim() !== snapshot?.name }" :cancel-btn="{ content: t('common.cancel'), disabled: busy }" :close-on-overlay-click="!busy" :close-on-esc-keydown="!busy" :close-btn="!busy" @close="() => { if (!busy) deleteVisible = false }" @confirm="remove">
      <p>{{ t('tenant.deleteDangerZone.confirmBody', { name: snapshot?.name || '' }) }}</p>
      <p>{{ t('tenant.deleteDangerZone.confirmHint', { name: snapshot?.name || '' }) }}</p>
      <t-input v-model="confirmationName" :aria-label="t('tenant.details.nameLabel')" :placeholder="snapshot?.name" :disabled="busy" />
      <t-alert v-if="error" theme="error" :message="error" />
    </t-dialog>
  </section>
</template>
<style scoped>
section { width: 100%; }
.enterprise-code { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-width: 0; }
.enterprise-code code { overflow-wrap: anywhere; }
.copy-error { color: var(--td-error-color); }
.info-actions { display: flex; gap: 12px; padding: 24px 0; }
:deep(.setting-control .t-input__wrap), :deep(.setting-control .t-textarea) { width: 320px; max-width: 100%; }
</style>
