<script setup lang="ts">
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import { useRoute } from 'vue-router'
import EditorDialog from '@nexus-web/core/components/settings/EditorDialog.vue'
/** 企业智能体渠道总览和个人 WeCom 渠道审核队列。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin, QRCode } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { beginWechatBinding, createAgentChannel, deleteAgentChannel, disableAgentChannel, fetchChannelPolicy, fetchWecomApps, pollWechatBinding, listChannelAgentNames, listEnterpriseChannels, reviewEnterpriseChannel, type AgentChannel, type ChannelStatus, type WecomAgentApp } from '@nexus-web/core/api/enterprise-connections'
import { useEnterpriseContext } from '../../stores/context'

const route = useRoute()
const { t } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('enterprise_agents:manage'))
const rows = ref<AgentChannel[]>([]), agents = ref<Awaited<ReturnType<typeof listChannelAgentNames>>>([]), ready = ref(false), loading = ref(false), busy = ref(false), error = ref('')
const filter = ref<'all' | ChannelStatus>('all'), rejection = ref<AgentChannel | null>(null), note = ref('')
const options = computed(() => ['all', 'pending_review', 'active', 'binding', 'rejected', 'disabled', 'expired'].map(value => ({ value, label: t(`adminChannels.status.${value}`) })))
const filterAgent = ref(typeof route.query.agent === 'string' ? route.query.agent : '')
const createOpen = ref(false), createError = ref(''), appsLoading = ref(false)
const apps = ref<WecomAgentApp[]>([]), draftAgent = ref(''), draftApp = ref(''), draftName = ref('')
const agentOptions = computed(() => agents.value.map(agent => ({ value: agent.id, label: agent.name })))
const canUseApps = computed(() => context.can('org:manage'))
const draftAgents = computed(() => agents.value.filter(agent => agent.canMaintainPublished
  && (agent.ownership === 'personal' || canUseApps.value)))
const createOptions = computed(() => draftAgents.value.map(agent => ({ value: agent.id, label: agent.name })))
const draftOwner = computed(() => draftAgents.value.find(agent => agent.id === draftAgent.value)?.ownership)
const draftPlatform = ref<'wecom' | 'wechat'>('wecom')
const externalAllowed = ref(false)
const step = ref(0)
const stepTitles = computed(() => [
  t('agentEditor.im.stepBasic'), t('agentEditor.im.stepConnection'),
  t('agentEditor.im.stepKnowledge'), t('agentEditor.im.stepCredentials'),
])
const platformOptions = computed(() => ['wecom', 'feishu', 'lark', 'slack', 'telegram', 'dingtalk', 'mattermost', 'wechat', 'qqbot', 'yunzhijia']
  .map(value => {
    const enabled = value === 'wecom' && canUseApps.value && draftOwner.value === 'enterprise'
      || value === 'wechat' && externalAllowed.value && draftOwner.value === 'personal'
    return { value, disabled: !enabled,
      label: value === 'wecom' || value === 'wechat' ? t(`agentEditor.im.${value}`)
        : `${t(`agentEditor.im.${value}`)} · ${t('enterpriseNav.unavailable')}` }
  }))
const validAgent = computed(() => !!draftOwner.value && platformOptions.value.some(option =>
  option.value === draftPlatform.value && !option.disabled))
const confirmDisabled = computed(() => appsLoading.value || !validAgent.value
  || (step.value === 3 && draftPlatform.value === 'wecom' && !draftApp.value))
const appOptions = computed(() => apps.value.filter(app => app.purpose === 'agent' && app.status === 'active' && app.nexus_agent_id === draftAgent.value)
  .map(app => ({ value: app.id, label: app.name })))
const visibleChannels = computed(() => rows.value.filter(row => !filterAgent.value || row.agent_id === filterAgent.value))
const canCreate = computed(() => !!createOptions.value.length)
watch(draftAgent, () => {
  draftApp.value = ''
  draftPlatform.value = draftOwner.value === 'personal' ? 'wechat' : 'wecom'
}, { flush: 'sync' })
const qrChannel = ref('')
const qrContent = ref('')
const qrExpired = ref(false)
const qrError = ref(false)
let qrTimer: ReturnType<typeof setTimeout> | undefined
let qrAttempt = 0
watch(() => route.query.agent, id => { filterAgent.value = typeof id === 'string' ? id : '' })
let formEpoch = 0
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; agents.value = []; ready.value = false; loading.value = false; busy.value = false; error.value = ''; rejection.value = null; note.value = ''; closeCreate(); closeBinding() }
async function load() {
  const current = ++epoch, scope = tenant.value; rows.value = []; agents.value = []; ready.value = false; error.value = ''
  if (!scope || !canManage.value) return
  loading.value = true
  try {
    const [channels, directory] = await Promise.all([listEnterpriseChannels(scope, filter.value === 'all' ? undefined : filter.value), listChannelAgentNames(scope)])
    if (current === epoch) { rows.value = channels; agents.value = directory; ready.value = true }
  } catch { if (current === epoch) error.value = t('adminChannels.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true, flush: 'sync' })
watch(filter, () => { if (canManage.value) void load() })
onBeforeUnmount(invalidate)
function channelKind(value: string) { return t(`adminChannels.kind.${value}`) }
function agentName(id: string) { return agents.value.find(agent => agent.id === id)?.name || t('adminChannels.unknownAgent') }
function closeReject() { if (busy.value) return; rejection.value = null; note.value = '' }
async function writeReview(row: AgentChannel, approve: boolean, reason = '') {
  if (!canManage.value || !ready.value || busy.value || !rows.value.includes(row) || row.status !== 'pending_review') return
  const current = epoch, scope = tenant.value; busy.value = true; error.value = ''
  try {
    const updated = await reviewEnterpriseChannel(scope, row.id, { approve, ...(reason.trim() ? { note: reason.trim() } : {}) })
    if (current !== epoch || !canManage.value) return
    rows.value = filter.value === 'all' ? rows.value.map(item => item.id === row.id ? updated : item) : rows.value.filter(item => item.id !== row.id)
    rejection.value = null; note.value = ''; MessagePlugin.success(t(approve ? 'adminChannels.approved' : 'adminChannels.rejected'))
  } catch { if (current === epoch) error.value = t('adminChannels.reviewFailed') }
  finally { if (current === epoch) busy.value = false }
}
function approve(row: AgentChannel) {
  if (confirmation || !ready.value || busy.value || row.status !== 'pending_review') return
  const current = epoch; let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminChannels.approveTitle'), body: t('adminChannels.approveConfirm', { channel: row.name || channelKind(row.kind), agent: agentName(row.agent_id) }),
    onConfirm: async () => { if (confirmation !== dialog) return; dialog.hide(); confirmation = undefined; if (current === epoch) await writeReview(row, true) },
    onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
function openReject(row: AgentChannel) { if (ready.value && !busy.value && row.status === 'pending_review' && rows.value.includes(row)) { rejection.value = row; note.value = '' } }
async function reject() { if (!rejection.value || note.value.trim().length < 1 || note.value.length > 500) return; await writeReview(rejection.value, false, note.value) }
/** 新增抽屉只读取当前企业已绑定的企业微信应用。 */
async function openCreate() {
  if (!canCreate.value || !ready.value || busy.value) return
  const scope = tenant.value, current = epoch, form = ++formEpoch
  draftAgent.value = createOptions.value.find(agent => agent.value === filterAgent.value)?.value ?? ''
  createOpen.value = true
  appsLoading.value = true
  try {
    const [entries, policy] = await Promise.all([
      canUseApps.value ? fetchWecomApps(scope) : Promise.resolve([]),
      draftAgents.value.some(agent => agent.ownership === 'personal') ? fetchChannelPolicy(scope) : Promise.resolve(null),
    ])
    if (current === epoch && form === formEpoch) {
      apps.value = entries
      externalAllowed.value = policy?.personal_external_channels ?? false
    }
  } catch {
    if (current === epoch && form === formEpoch) createError.value = t('adminChannels.loadFailed')
  } finally {
    if (current === epoch && form === formEpoch) appsLoading.value = false
  }
}
function closeCreate() {
  formEpoch++
  createOpen.value = false
  appsLoading.value = false
  step.value = 0
  externalAllowed.value = false
  apps.value = []
  draftAgent.value = ''
  draftApp.value = ''
  draftName.value = ''
  createError.value = ''
}
async function confirmStep() {
  if (confirmDisabled.value || busy.value) return
  if (step.value < stepTitles.value.length - 1) {
    step.value++
    return
  }
  await createChannel()
}
async function createChannel() {
  if (!canManage.value || !canCreate.value || !createOpen.value || busy.value || appsLoading.value
    || !validAgent.value || (draftPlatform.value === 'wecom' && !appOptions.value.some(app => app.value === draftApp.value))) return
  const current = epoch
  busy.value = true
  createError.value = ''
  try {
    const platform = draftPlatform.value
    const row = await createAgentChannel(tenant.value, draftAgent.value, {
      kind: platform === 'wechat' ? 'wechat' : 'wecom_app',
      name: draftName.value.trim() || t(`agentEditor.im.${platform}`),
      ...(platform === 'wecom' ? { wecom_app_id: draftApp.value } : {}),
    })
    if (current !== epoch) return
    filterAgent.value = draftAgent.value
    closeCreate()
    if (row.kind === 'wechat' && row.status === 'binding') void openBinding(row)
    if (filter.value !== 'all') {
      busy.value = false
      filter.value = 'all'
    } else {
      busy.value = false
      await load()
    }
  } catch {
    if (current === epoch) createError.value = t('connectionUi.failed')
  } finally {
    if (current === epoch) busy.value = false
  }
}
/** 绑定二维码只在当前账号的弹层内生成，关闭或切换企业停止轮询。 */
async function openBinding(row: AgentChannel) {
  if (row.kind !== 'wechat' || row.status !== 'binding' || row.owner_user_id !== auth.user?.id) return
  closeBinding()
  const tenantId = tenant.value, attempt = qrAttempt
  qrChannel.value = row.id
  const live = () => qrAttempt === attempt && qrChannel.value === row.id
  const poll = async () => {
    if (!live()) return
    try {
      const result = await pollWechatBinding(tenantId, row.id)
      if (!live()) return
      if (result.status === 'confirmed') {
        closeBinding()
        await load()
      } else if (result.status === 'expired') {
        qrExpired.value = true
      } else {
        qrTimer = setTimeout(() => { void poll() }, 1500)
      }
    } catch {
      if (live()) qrError.value = true
    }
  }
  try {
    const content = await beginWechatBinding(tenantId, row.id)
    if (!live()) return
    qrContent.value = content
    qrTimer = setTimeout(() => { void poll() }, 1500)
  } catch {
    if (live()) qrError.value = true
  }
}
function closeBinding() {
  qrAttempt++
  clearTimeout(qrTimer)
  qrChannel.value = ''
  qrContent.value = ''
  qrExpired.value = false
  qrError.value = false
}

async function changeChannel(row: AgentChannel, remove: boolean) {
  if (!canManage.value || !ready.value || busy.value || !rows.value.includes(row)) return
  const current = epoch, scope = tenant.value
  busy.value = true
  error.value = ''
  try {
    await (remove ? deleteAgentChannel : disableAgentChannel)(scope, row.id)
    if (current === epoch) {
      rows.value = remove || (filter.value !== 'all' && filter.value !== 'disabled')
        ? rows.value.filter(item => item.id !== row.id)
        : rows.value.map(item => item.id === row.id ? { ...item, status: 'disabled' } : item)
    }
  } catch {
    if (current === epoch) error.value = t('connectionUi.failed')
  } finally {
    if (current === epoch) busy.value = false
  }
}
</script>

<template>
  <section class="im-panel">
    <header class="section-header">
      <div><h2>{{ t('integrations.tabs.im') }}</h2><p>{{ t('adminChannels.description') }}</p></div>
      <t-button variant="outline" :loading="loading" :disabled="busy || createOpen" @click="load">{{ t('connectionUi.refresh') }}</t-button>
    </header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <div class="channels-section">
        <div class="channels-header">
          <span class="channels-title">{{ t('agentEditor.im.channelsTitle') }}</span>
          <t-select v-model="filterAgent" :options="agentOptions" filterable clearable
            :placeholder="t('adminChannels.agent')" :aria-label="t('adminChannels.agent')" />
          <span class="channels-count">{{ visibleChannels.length }}</span>
          <t-select v-model="filter" :options="options" :disabled="busy || createOpen" :aria-label="t('adminChannels.filter')" />
        </div>
        <t-loading :loading="loading" size="small" class="channels-loading-wrap">
          <div v-if="ready" class="channel-grid">
            <article v-for="row in visibleChannels" :key="row.id" class="channel-card">
              <div class="channel-card__badge"><t-icon name="chat-message" size="22px" aria-hidden="true" /></div>
              <div class="channel-card__body">
                <div class="channel-card__header">
                  <h3 class="channel-card__title">{{ row.name || channelKind(row.kind) }}</h3>
                  <t-tag size="small" variant="light" :theme="row.status === 'active' ? 'success' : 'default'">{{ t(`adminChannels.status.${row.status}`) }}</t-tag>
                </div>
                <span class="channel-card__agent-name">{{ agentName(row.agent_id) }} · {{ channelKind(row.kind) }}</span>
                <p v-if="row.review_note" class="note">{{ row.review_note }}</p>
                <div v-if="row.status === 'pending_review'" class="channel-review">
                  <t-button variant="text" :disabled="busy" @click="approve(row)">{{ t('adminChannels.approve') }}</t-button>
                  <t-button variant="text" theme="danger" :disabled="busy" @click="openReject(row)">{{ t('adminChannels.reject') }}</t-button>
                </div>
              </div>
              <div class="channel-card__actions">
                <t-button v-if="row.kind === 'wechat' && row.status === 'binding' && row.owner_user_id === auth.user?.id"
                  variant="text" size="small" :disabled="busy" @click="openBinding(row)">{{ t('connectionUi.bind') }}</t-button>
                <t-popconfirm v-if="row.status !== 'disabled'" :content="t('connectionUi.disableConfirm')" @confirm="changeChannel(row, false)">
                  <t-button variant="text" shape="square" size="small" :disabled="busy" :aria-label="t('connectionUi.disable')">
                    <template #icon><t-icon name="close-circle" aria-hidden="true" /></template>
                  </t-button>
                </t-popconfirm>
                <t-popconfirm :content="t('connectionUi.deleteConfirm')" @confirm="changeChannel(row, true)">
                  <t-button variant="text" theme="danger" shape="square" size="small" :disabled="busy" :aria-label="t('common.delete')">
                    <template #icon><t-icon name="delete" aria-hidden="true" /></template>
                  </t-button>
                </t-popconfirm>
              </div>
            </article>
            <button v-if="canCreate" type="button" class="channel-card channel-card--add" :disabled="busy" @click="openCreate">
              <span class="channel-card__badge" aria-hidden="true"><t-icon name="add" /></span>
              <span class="channel-card__title">{{ t('agentEditor.im.addChannel') }}</span>
            </button>
            <t-empty v-if="!visibleChannels.length && !canCreate" :description="t('adminChannels.empty')" />
          </div>
        </t-loading>
      </div>
      <SettingDrawer :visible="createOpen" :title="t('agentEditor.im.addChannel')" :description="stepTitles[step]" icon="chat-message"
        :confirm-text="t(step < 3 ? 'common.next' : 'common.save')" :confirm-disabled="confirmDisabled" :confirm-loading="busy"
        :cancel-disabled="busy" :close-btn="!busy" :close-on-overlay-click="!busy" :close-on-esc-keydown="!busy"
        @confirm="confirmStep" @update:visible="(value: boolean) => { if (!value && !busy) closeCreate() }">
        <template v-if="step > 0" #footer-left>
          <t-button variant="outline" :disabled="busy" @click="step--">{{ t('common.back') }}</t-button>
        </template>
        <div class="im-steps">
          <div v-for="(title, index) in stepTitles" :key="title" class="im-step"
            :class="{ active: index === step, done: index < step }" :aria-current="index === step ? 'step' : undefined">
            <span class="im-step-num" aria-hidden="true">
              <t-icon v-if="index < step" name="check" class="im-step-check" /><template v-else>{{ index + 1 }}</template>
            </span>
            <span class="im-step-title" :title="title">{{ title }}</span>
          </div>
        </div>
        <t-alert v-if="createError" theme="error" :message="createError" />
        <section v-if="step === 0" class="setting-drawer__section im-form">
          <h4 class="setting-drawer__section-title">{{ t('agentEditor.im.sectionChannel') }}</h4>
          <label>{{ t('adminChannels.agent') }}<t-select v-model="draftAgent" :options="createOptions" filterable /></label>
          <label>{{ t('agentEditor.im.platform') }}
            <t-select v-model="draftPlatform" :options="platformOptions" :loading="appsLoading" />
          </label>
          <t-alert v-if="draftOwner === 'personal' && !appsLoading && !externalAllowed" theme="warning" :message="t('connectionUi.policyBlocked')" />
          <label>{{ t('adminChannels.channel') }}
            <t-input v-model="draftName" :maxlength="80" :placeholder="t('agentEditor.im.channelNamePlaceholder')" />
          </label>
        </section>
        <section v-else-if="step === 1" class="setting-drawer__section im-form">
          <h4 class="setting-drawer__section-title">{{ t('agentEditor.im.sectionAccess') }}</h4>
          <p>{{ t('agentEditor.im.mode') }} <t-tag>{{ draftPlatform === 'wecom' ? 'Webhook' : t('connectionUi.bind') }}</t-tag></p>
        </section>
        <section v-else-if="step === 2" class="setting-drawer__section im-form">
          <h4 class="setting-drawer__section-title">{{ t('agentEditor.im.stepKnowledge') }}</h4>
          <p>{{ t('enterpriseNav.imKnowledge') }}</p>
        </section>
        <section v-else class="setting-drawer__section im-form">
          <h4 class="setting-drawer__section-title">{{ t('agentEditor.im.sectionCredentials') }}</h4>
          <template v-if="draftPlatform === 'wecom'">
            <label>{{ t('connectionUi.wecomApp') }}
              <t-select v-model="draftApp" :options="appOptions" :loading="appsLoading" :disabled="busy || appsLoading" />
            </label>
            <t-alert v-if="!appsLoading && !createError && !appOptions.length" theme="info" :message="t('connectionUi.appRequired')" />
            <RouterLink v-if="!busy" to="/wecom">{{ t('enterpriseNav.imCredentials') }}</RouterLink>
          </template>
          <p v-else>{{ t('connectionUi.bindHint') }}</p>
        </section>
      </SettingDrawer>
      <EditorDialog :visible="!!qrChannel" :header="t('connectionUi.bind')" :footer="false" @close="closeBinding">
        <t-alert v-if="qrError" theme="error" :message="t('connectionUi.failed')" />
        <p v-else-if="qrExpired">{{ t('connectionUi.qrExpired') }}</p>
        <QRCode v-else-if="qrContent" :value="qrContent" :size="220" />
        <t-loading v-else :loading="true" />
        <p v-if="qrContent && !qrExpired && !qrError">{{ t('connectionUi.qrWaiting') }}</p>
      </EditorDialog>
      <EditorDialog :visible="!!rejection" :header="t('adminChannels.rejectTitle')" :confirm-btn="{ content: t('adminChannels.reject'), theme: 'danger', disabled: !note.trim() || note.length > 500, loading: busy }" :cancel-btn="{ content: t('common.cancel'), disabled: busy }" @confirm="reject" @close="closeReject"><p v-if="rejection">{{ t('adminChannels.rejectConfirm', { channel: rejection.name || channelKind(rejection.kind), agent: agentName(rejection.agent_id) }) }}</p><label class="reason-label">{{ t('adminChannels.reason') }}<t-textarea v-model="note" :maxlength="500" :autosize="{ minRows: 3, maxRows: 6 }" :disabled="busy" /></label></EditorDialog>
    </template>
  </section>
</template>

<style scoped lang="less">
@import '@nexus-web/core/styles/channel-panel-list.less';
@import './ChannelWizard.reference.less';

.channels-header { flex-wrap: wrap; }
.channels-header :deep(.t-select__wrap) { width: min(11rem, 100%); }
.channel-review { display: flex; flex-wrap: wrap; margin-top: 4px; }
.note { margin: 6px 0 0; color: var(--td-text-color-secondary); white-space: pre-wrap; overflow-wrap: anywhere; }
.im-form, .im-form label, .reason-label { display: grid; gap: 8px; }
.reason-label { margin-top: 16px; }
.im-form p { margin: 0; }
</style>
