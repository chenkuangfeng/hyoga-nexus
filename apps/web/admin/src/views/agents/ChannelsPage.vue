<script setup lang="ts">
/** 企业智能体渠道总览和个人 WeCom 渠道审核队列。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { listChannelAgentNames, listEnterpriseChannels, reviewEnterpriseChannel, type AgentChannel, type ChannelStatus } from '@nexus-web/core/api/enterprise-connections'
import { useAdminContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('enterprise_agents:manage'))
const rows = ref<AgentChannel[]>([]), agentNames = ref<Record<string, string>>({}), ready = ref(false), loading = ref(false), busy = ref(false), error = ref('')
const filter = ref<'all' | ChannelStatus>('pending_review'), rejection = ref<AgentChannel | null>(null), note = ref('')
const options = computed(() => ['all', 'pending_review', 'active', 'binding', 'rejected', 'disabled', 'expired'].map(value => ({ value, label: t(`adminChannels.status.${value}`) })))
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; agentNames.value = {}; ready.value = false; loading.value = false; busy.value = false; error.value = ''; rejection.value = null; note.value = '' }
async function load() {
  const current = ++epoch, scope = tenant.value; rows.value = []; agentNames.value = {}; ready.value = false; error.value = ''
  if (!scope || !canManage.value) return
  loading.value = true
  try {
    const [channels, agents] = await Promise.all([listEnterpriseChannels(scope, filter.value === 'all' ? undefined : filter.value), listChannelAgentNames(scope)])
    if (current === epoch) { rows.value = channels; agentNames.value = Object.fromEntries(agents.map(agent => [agent.id, agent.name])); ready.value = true }
  } catch { if (current === epoch) error.value = t('adminChannels.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
watch(filter, () => { if (canManage.value) void load() })
onBeforeUnmount(invalidate)
function channelKind(value: string) { return t(`adminChannels.kind.${value}`) }
function agentName(id: string) { return agentNames.value[id] || t('adminChannels.unknownAgent') }
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
</script>

<template>
  <section class="channels-page">
    <header class="section-header"><div><h2>{{ t('adminChannels.title') }}</h2><p>{{ t('adminChannels.description') }}</p></div><div class="actions"><t-select v-model="filter" :options="options" :disabled="busy" :aria-label="t('adminChannels.filter')" /><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></div></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-alert theme="info" :message="t('adminChannels.scopeHint')" />
      <t-loading :loading="loading"><div v-if="ready" class="table-shell"><table><thead><tr><th>{{ t('adminChannels.agent') }}</th><th>{{ t('adminChannels.channel') }}</th><th>{{ t('adminChannels.kindLabel') }}</th><th>{{ t('adminChannels.statusLabel') }}</th><th>{{ t('adminChannels.created') }}</th><th>{{ t('adminChannels.actions') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ agentName(row.agent_id) }}</td><td>{{ row.name || channelKind(row.kind) }}</td><td>{{ channelKind(row.kind) }}</td><td><t-tag :theme="row.status === 'pending_review' ? 'warning' : row.status === 'active' ? 'success' : 'default'" variant="light">{{ t(`adminChannels.status.${row.status}`) }}</t-tag><p v-if="row.review_note" class="note">{{ row.review_note }}</p></td><td>{{ row.created_at || '—' }}</td><td><div v-if="row.status === 'pending_review'" class="actions"><t-button variant="text" theme="primary" :disabled="busy" @click="approve(row)">{{ t('adminChannels.approve') }}</t-button><t-button variant="text" theme="danger" :disabled="busy" @click="openReject(row)">{{ t('adminChannels.reject') }}</t-button></div><span v-else>—</span></td></tr><tr v-if="!rows.length"><td colspan="6">{{ t('adminChannels.empty') }}</td></tr></tbody></table></div></t-loading>
      <t-dialog :visible="!!rejection" :header="t('adminChannels.rejectTitle')" :confirm-btn="{ content: t('adminChannels.reject'), theme: 'danger', disabled: !note.trim() || note.length > 500, loading: busy }" :cancel-btn="{ content: t('common.cancel'), disabled: busy }" @confirm="reject" @close="closeReject"><p v-if="rejection">{{ t('adminChannels.rejectConfirm', { channel: rejection.name || channelKind(rejection.kind), agent: agentName(rejection.agent_id) }) }}</p><label class="reason-label">{{ t('adminChannels.reason') }}<t-textarea v-model="note" :maxlength="500" :autosize="{ minRows: 3, maxRows: 6 }" :disabled="busy" /></label></t-dialog>
    </template>
  </section>
</template>

<style scoped>
.channels-page { min-width: 0; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.section-header .actions :deep(.t-select) { width: 180px; }
.table-shell { max-width: 100%; overflow-x: auto; margin-top: 16px; }
table { width: 100%; min-width: 760px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); vertical-align: top; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
.note { margin: 6px 0 0; color: var(--td-text-color-secondary); white-space: pre-wrap; }
.reason-label { display: grid; gap: 8px; margin-top: 16px; }
@media (max-width: 600px) { .section-header { align-items: flex-start; flex-direction: column; } }
</style>
