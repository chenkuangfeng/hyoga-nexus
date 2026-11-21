<script setup lang="ts">
/** 企业智能体使用授权。独立读取与确认代次，不把候选可见性视为操作者可授予权限。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useEnterpriseContext } from '../../stores/context'
import { listRoleAgentChoices, listRoleAgentGrants, setRoleAgentGrants, type EnterpriseRole, type RoleAgentChoice, type RoleAgentGrant, type AgentUsePermission } from '@nexus-web/core/api/enterprise-roles'
const props = defineProps<{ roles: EnterpriseRole[]; disabled: boolean; refreshPermissions: (tenant: string, user: string | undefined, result?: string) => Promise<void> }>()
const auth = useAuthStore(), context = useEnterpriseContext(), { t } = useI18n()
const agents = ref<RoleAgentChoice[]>([]), grants = ref<RoleAgentGrant[]>([])
const loading = ref(false), ready = ref(false), busy = ref(false), error = ref('')
const selectedRole = ref(''), selectedAgent = ref(''), permissions = ref<AgentUsePermission[]>([])
let epoch = 0, selectionEpoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
const canManage = computed(() => context.can('roles:manage'))
const knownPair = computed(() => props.roles.some(row => row.id === selectedRole.value) && agents.value.some(row => row.id === selectedAgent.value))
const existing = computed(() => [...new Set(grants.value.filter(row => row.role_id === selectedRole.value && row.agent_id === selectedAgent.value).map(row => row.permission))])
const dirty = computed(() => permissions.value.length !== existing.value.length || permissions.value.some(p => !existing.value.includes(p)))
const canSave = computed(() => ready.value && canManage.value && knownPair.value && dirty.value && !busy.value && !loading.value && !props.disabled && permissions.value.every(p => p === 'view' || p === 'run') && new Set(permissions.value).size === permissions.value.length)
const unresolved = computed(() => new Set(grants.value.filter(row => !agents.value.some(agent => agent.id === row.agent_id) || !props.roles.some(role => role.id === row.role_id)).map(row => `${row.role_id}:${row.agent_id}`)).size)
const rows = computed(() => {
  const pairs = new Map<string, { role: string; agent: string; permissions: AgentUsePermission[] }>()
  for (const grant of grants.value) {
    const role = props.roles.find(row => row.id === grant.role_id), agent = agents.value.find(row => row.id === grant.agent_id)
    if (!role || !agent) continue
    const key = `${grant.role_id}:${grant.agent_id}`, row = pairs.get(key) || { role: role.name, agent: agent.name, permissions: [] }
    if (!row.permissions.includes(grant.permission)) row.permissions.push(grant.permission)
    pairs.set(key, row)
  }
  return [...pairs.entries()].map(([key, row]) => ({ key, ...row }))
})
function failure(reason: unknown) { return reason && typeof reason === 'object' && 'message' in reason && typeof reason.message === 'string' && reason.message !== 'roles_response_invalid' ? reason.message : t('adminConsole.failed') }
function cancelConfirmation() { selectionEpoch++; confirmation?.hide(); confirmation = undefined }
async function load() {
  const current = ++epoch
  cancelConfirmation(); ready.value = false; agents.value = []; grants.value = []; selectedRole.value = ''; selectedAgent.value = ''; permissions.value = []; error.value = ''; loading.value = false
  if (!canManage.value || busy.value) return
  const tenant = String(auth.effectiveTenantId)
  loading.value = true
  const result = await Promise.allSettled([listRoleAgentChoices(tenant), listRoleAgentGrants(tenant)])
  if (current !== epoch) return
  if (result[0].status === 'fulfilled' && result[1].status === 'fulfilled') { agents.value = result[0].value; grants.value = result[1].value; ready.value = true }
  else error.value = t('adminConsole.failed')
  loading.value = false
}
function save() {
  if (!canSave.value || confirmation) return
  const current = epoch, selection = selectionEpoch, tenant = String(auth.effectiveTenantId), user = auth.user?.id
  const role = selectedRole.value, agent = selectedAgent.value, input = [...permissions.value]
  const dialog = DialogPlugin.confirm({
    header: t('adminAgentGrants.confirm'), body: t(input.length ? 'adminAgentGrants.saveConfirm' : 'adminAgentGrants.revokeConfirm', { role: props.roles.find(row => row.id === role)!.name, agent: agents.value.find(row => row.id === agent)!.name, permissions: input.map(p => t(`adminAgentGrants.${p}`)).join(' / ') }),
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (current !== epoch || selection !== selectionEpoch || !canSave.value) return
      busy.value = true; error.value = ''
      try { await setRoleAgentGrants(tenant, role, agent, input) }
      catch (reason) { if (current === epoch) { error.value = failure(reason); busy.value = false }; return }
      if (current !== epoch || selection !== selectionEpoch || auth.user?.id !== user || String(auth.effectiveTenantId) !== tenant) return
      await props.refreshPermissions(tenant, user, t('adminAgentGrants.saved'))
      // 实际外壳会因权限校准卸载本区；若仍挂载，读取服务端事实而非伪造本地结果。
      if (current === epoch) { busy.value = false; await load() }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
watch([selectedRole, selectedAgent], () => { cancelConfirmation(); permissions.value = [...existing.value]; error.value = '' }, { flush: 'sync' })
watch([() => auth.effectiveTenantId, () => auth.user?.id, () => context.revision, canManage, () => props.roles], () => { busy.value = false; void load() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { epoch++; cancelConfirmation() })
</script>
<template>
  <section class="agent-grants-panel">
    <header><h3>{{ t('adminAgentGrants.title') }}</h3><t-button variant="outline" :loading="loading" :disabled="busy || disabled" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <p class="hint">{{ t('adminAgentGrants.scopeHint') }}</p>
    <p class="hint">{{ t('adminAgentGrants.revokeHint') }}</p>
    <t-alert v-if="error" theme="error" :message="error" />
    <t-loading :loading="loading">
      <template v-if="ready">
        <t-alert v-if="unresolved" theme="warning" :message="t('adminAgentGrants.unresolved', { count: unresolved })" />
        <t-alert v-if="!agents.length" theme="info" :message="t('adminAgentGrants.noAgents')" />
        <div class="grant-form">
          <t-select v-model="selectedRole" :options="roles.map(row => ({ value: row.id, label: row.name }))" :placeholder="t('adminRoles.role')" :aria-label="t('adminRoles.role')" :disabled="busy || disabled" filterable />
          <t-select v-model="selectedAgent" :options="agents.map(row => ({ value: row.id, label: row.name }))" :placeholder="t('adminAgentGrants.agent')" :aria-label="t('adminAgentGrants.agent')" :disabled="busy || disabled" filterable />
          <t-checkbox-group v-model="permissions" :disabled="busy || disabled || !knownPair" :aria-label="t('adminRoles.permissions')"><t-checkbox value="view">{{ t('adminAgentGrants.view') }}</t-checkbox><t-checkbox value="run">{{ t('adminAgentGrants.run') }}</t-checkbox></t-checkbox-group>
          <t-button theme="primary" :loading="busy" :disabled="!canSave" @click="save">{{ t(permissions.length ? 'common.save' : 'adminAgentGrants.revoke') }}</t-button>
        </div>
        <div class="grant-table"><table><thead><tr><th>{{ t('adminRoles.role') }}</th><th>{{ t('adminAgentGrants.agent') }}</th><th>{{ t('adminRoles.permissions') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.key"><td>{{ row.role }}</td><td>{{ row.agent }}</td><td>{{ row.permissions.map(p => t(`adminAgentGrants.${p}`)).join(' / ') }}</td></tr><tr v-if="!rows.length"><td colspan="3">{{ t('adminAgentGrants.empty') }}</td></tr></tbody></table></div>
      </template>
    </t-loading>
  </section>
</template>
<style scoped>
header, .grant-form { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
header { justify-content: space-between; margin-top: 32px; }
h3 { margin: 0; font-size: var(--app-text-xl); }
.hint { color: var(--td-text-color-secondary); line-height: 1.6; }
.grant-form { margin: 16px 0; }
.grant-form :deep(.t-select__wrap) { width: 240px; max-width: 100%; }
.grant-table { overflow-x: auto; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); }
table { width: 100%; border-collapse: collapse; text-align: left; }
th, td { padding: 12px 16px; border-bottom: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
</style>
