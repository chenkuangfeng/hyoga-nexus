<script setup lang="ts">
/** 智能体维护者的渠道面板；权限、归属、企业策略和平台核验均以服务端为准。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { QRCode } from 'tdesign-vue-next'
import { useAuthStore } from '../stores/auth'
import { beginWechatBinding, createAgentChannel, deleteAgentChannel, disableAgentChannel, fetchChannelPolicy, fetchConnectionPermissions, fetchWecomApps, listAgentChannels, pollWechatBinding, type AgentChannel, type ChannelKind, type WecomAgentApp } from '../api/enterprise-connections'

const props = defineProps<{ tenantId: string; agentId: string; ownership: 'personal' | 'enterprise' }>()
const { t } = useI18n()
const auth = useAuthStore()
const channels = ref<AgentChannel[]>([])
const unverified = ref<string[]>([])
const apps = ref<WecomAgentApp[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const ready = ref(false)
const externalAllowed = ref(false)
const name = ref('')
const appId = ref('')
const kind = ref<ChannelKind>('wechat')
const bindingId = ref('')
const qrContent = ref('')
const qrStatus = ref('wait')
let epoch = 0
let qrAttempt = 0
let timer: ReturnType<typeof setTimeout> | undefined
const availableKinds = computed<ChannelKind[]>(() => props.ownership === 'personal' ? ['wechat', 'wecom_bot', 'qq'] : ['wecom_app', 'wecom_bot'])
const appOptions = computed(() => apps.value.filter(app => app.purpose === 'agent' && app.nexus_agent_id === props.agentId && app.status === 'active').map(app => ({ label: app.name, value: app.id })))
const allowed = computed(() => ready.value && !unverified.value.includes(kind.value) && (props.ownership === 'enterprise' ? kind.value === 'wecom_app' && !!appId.value : kind.value === 'wechat' && externalAllowed.value))
function message(reason: unknown): string { return reason instanceof Error && reason.message !== 'connection_response_invalid' ? reason.message : t('connectionUi.failed') }
function stopBinding() { qrAttempt++; if (timer) clearTimeout(timer); timer = undefined; bindingId.value = ''; qrContent.value = ''; qrStatus.value = 'wait' }
async function reload() {
  const current = ++epoch
  stopBinding(); channels.value = []; apps.value = []; ready.value = false; busy.value = false; error.value = ''; loading.value = true; name.value = ''; appId.value = ''
  kind.value = props.ownership === 'personal' ? 'wechat' : 'wecom_app'
  const tenantId = props.tenantId, agentId = props.agentId
  try {
    const list = await listAgentChannels(tenantId, agentId)
    if (current !== epoch) return
    channels.value = list.items; unverified.value = list.unverified
    const [policy, permissions] = await Promise.all([fetchChannelPolicy(tenantId), fetchConnectionPermissions(tenantId)])
    if (current !== epoch) return
    const configured = props.ownership === 'enterprise' && permissions.includes('org:manage') ? await fetchWecomApps(tenantId) : []
    if (current !== epoch) return
    externalAllowed.value = policy.personal_external_channels; apps.value = configured; ready.value = true
  } catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) loading.value = false }
}
async function create() {
  if (!allowed.value || busy.value) return
  const current = epoch, tenantId = props.tenantId, agentId = props.agentId
  busy.value = true; error.value = ''
  try {
    await createAgentChannel(tenantId, agentId, { kind: kind.value, name: name.value.trim(), ...(kind.value === 'wecom_app' ? { wecom_app_id: appId.value } : {}) })
    if (current === epoch) await reload()
  } catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) busy.value = false }
}
async function change(row: AgentChannel, remove: boolean) {
  if (busy.value || !channels.value.some(item => item.id === row.id)) return
  const current = epoch, tenantId = props.tenantId
  busy.value = true; error.value = ''
  try { await (remove ? deleteAgentChannel(tenantId, row.id) : disableAgentChannel(tenantId, row.id)); if (current === epoch) await reload() }
  catch (reason) { if (current === epoch) error.value = message(reason) }
  finally { if (current === epoch) busy.value = false }
}
async function bind(row: AgentChannel) {
  if (busy.value || row.kind !== 'wechat' || !channels.value.some(item => item.id === row.id) || row.owner_user_id !== auth.user?.id || row.status !== 'binding') return
  stopBinding()
  const current = epoch, attempt = qrAttempt, tenantId = props.tenantId
  const live = () => current === epoch && attempt === qrAttempt && bindingId.value === row.id
  bindingId.value = row.id; busy.value = true; error.value = ''
  try {
    const content = await beginWechatBinding(tenantId, row.id)
    if (!live()) return
    qrContent.value = content
    const poll = async () => {
      if (!live()) return
      try {
        const result = await pollWechatBinding(tenantId, row.id)
        if (!live()) return
        qrStatus.value = result.status
        if (result.status === 'confirmed') { await reload(); return }
        if (result.status !== 'expired') timer = setTimeout(() => { void poll() }, 1500)
      } catch (reason) { if (live()) { error.value = message(reason); stopBinding() } }
    }
    timer = setTimeout(() => { void poll() }, 1500)
  } catch (reason) { if (live()) { error.value = message(reason); stopBinding() } }
  finally { if (current === epoch) busy.value = false }
}
watch([() => props.tenantId, () => props.agentId, () => props.ownership, () => auth.user?.id], () => { void reload() }, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { epoch++; stopBinding() })
</script>

<template>
  <section class="connection-panel">
    <t-alert v-if="error" theme="error" :message="error" />
    <div class="connection-toolbar"><h2>{{ t('connectionUi.channels') }}</h2><t-button variant="outline" :loading="loading" @click="reload">{{ t('connectionUi.refresh') }}</t-button></div>
    <t-loading :loading="loading">
      <p v-if="!loading && !channels.length">{{ t('connectionUi.noChannels') }}</p>
      <article v-for="row in channels" :key="row.id" class="connection-card">
        <div><strong>{{ row.name }}</strong><p>{{ t(`connectionUi.kinds.${row.kind}`) }} · {{ t(`connectionUi.status.${row.status}`) }}</p><p v-if="row.review_note">{{ row.review_note }}</p></div>
        <div class="connection-actions">
          <t-button v-if="row.kind === 'wechat' && row.status === 'binding' && row.owner_user_id === auth.user?.id" :disabled="busy" @click="bind(row)">{{ t('connectionUi.bind') }}</t-button>
          <t-popconfirm v-if="row.status !== 'disabled'" :content="t('connectionUi.disableConfirm')" @confirm="change(row, false)"><t-button :disabled="busy" variant="outline">{{ t('connectionUi.disable') }}</t-button></t-popconfirm>
          <t-popconfirm :content="t('connectionUi.deleteConfirm')" @confirm="change(row, true)"><t-button :disabled="busy" variant="outline" theme="danger">{{ t('common.delete') }}</t-button></t-popconfirm>
        </div>
      </article>
    </t-loading>
    <t-form class="connection-form" layout="vertical" :disabled="busy || loading" @submit="({ validateResult }: { validateResult: unknown }) => { if (validateResult === true) create() }">
      <t-form-item :label="t('connectionUi.kind')"><t-select v-model="kind" :options="availableKinds.map(value => ({ value, label: t(`connectionUi.kinds.${value}`), disabled: unverified.includes(value) || !['wechat', 'wecom_app'].includes(value) }))" /></t-form-item>
      <t-alert v-if="props.ownership === 'personal' && ready && !externalAllowed" theme="warning" :message="t('connectionUi.policyBlocked')" />
      <t-alert v-if="props.ownership === 'enterprise' && !appOptions.length" theme="info" :message="t('connectionUi.appRequired')" />
      <t-form-item v-if="kind === 'wecom_app'" :label="t('connectionUi.wecomApp')"><t-select v-model="appId" :options="appOptions" /></t-form-item>
      <t-form-item :label="t('connectionUi.name')"><t-input v-model="name" :maxlength="80" /></t-form-item>
      <p>{{ t('connectionUi.unverified') }}</p>
      <t-button type="submit" theme="primary" :disabled="!allowed" :loading="busy">{{ t('connectionUi.create') }}</t-button>
    </t-form>
    <t-dialog :visible="!!bindingId" :header="t('connectionUi.bind')" :footer="false" @close="stopBinding">
      <p>{{ t('connectionUi.bindHint') }}</p>
      <QRCode v-if="qrContent" :value="qrContent" :size="220" />
      <t-loading v-else :loading="true" />
      <p>{{ qrStatus === 'expired' ? t('connectionUi.qrExpired') : t('connectionUi.qrWaiting') }}</p>
    </t-dialog>
  </section>
</template>

<style scoped>
.connection-panel { display: grid; gap: 16px; }
.connection-toolbar,.connection-card,.connection-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.connection-toolbar,.connection-card { justify-content: space-between; }
.connection-card { padding: 16px; border: 1px solid var(--td-component-border); border-radius: var(--td-radius-default); }
.connection-form { max-width: 560px; }
h2,p { margin: 8px 0; }
</style>
