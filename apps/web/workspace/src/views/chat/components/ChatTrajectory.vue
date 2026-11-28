<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConversationMessage, RunTrajectoryRecord } from '@nexus-web/core/api/native-runs'

interface ToolCallSnapshot {
  id: string
  name: string
  arguments: string
}

interface Activity {
  id: string
  runId: string
  sequence: number
  turn: number | null
  kind: 'user' | 'assistant' | 'tool'
  summary: string
  content: string
  createdAt: string
  status: string
  records: RunTrajectoryRecord[]
  toolName?: string
  toolArguments?: string
  toolResult?: string
}

const props = defineProps<{
  records: readonly RunTrajectoryRecord[]
  messages: readonly ConversationMessage[]
  loading: boolean
  error: boolean
}>()
const emit = defineEmits<{ retry: [] }>()
const { t } = useI18n()
const selectedId = ref('')

function object(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null
}

function calls(record: RunTrajectoryRecord): ToolCallSnapshot[] {
  const value = record.response_snapshot.tool_calls
  if (!Array.isArray(value)) return []
  return value.flatMap(item => {
    const row = object(item)
    if (!row || typeof row.id !== 'string' || typeof row.name !== 'string') return []
    return [{ id: row.id, name: row.name, arguments: typeof row.arguments === 'string' ? row.arguments : '' }]
  })
}

const activities = computed<Activity[]>(() => {
  const all: Activity[] = []
  const recordsByRun = new Map<string, RunTrajectoryRecord[]>()
  const messagesByRun = new Map<string, ConversationMessage[]>()
  const resultsByCall = new Map<string, ConversationMessage>()
  for (const record of props.records) recordsByRun.set(record.run_id, [...(recordsByRun.get(record.run_id) ?? []), record])
  for (const message of props.messages) {
    if (!message.run_id) continue
    messagesByRun.set(message.run_id, [...(messagesByRun.get(message.run_id) ?? []), message])
    if (message.role === 'tool' && message.tool_call_id) resultsByCall.set(`${message.run_id}:${message.tool_call_id}`, message)
  }
  for (const [runId, runMessages] of messagesByRun) {
    const runRecords = (recordsByRun.get(runId) ?? []).slice().sort((a, b) => a.sequence - b.sequence)
    const recordsByTurn = new Map<number, RunTrajectoryRecord[]>()
    for (const record of runRecords) recordsByTurn.set(record.turn, [...(recordsByTurn.get(record.turn) ?? []), record])
    const used = new Set<string>()
    let assistantTurn = 0
    const orderedMessages = runMessages.slice().sort((a, b) => a.sequence - b.sequence)
    for (const message of orderedMessages) {
      if (message.role === 'user') {
        all.push({ id: `message:${message.id}`, runId, sequence: message.sequence, turn: assistantTurn + 1,
          kind: 'user', summary: message.content, content: message.content, createdAt: message.created_at,
          status: 'completed', records: [] })
        continue
      }
      if (message.role === 'assistant') {
        assistantTurn += 1
        const turnRecords = recordsByTurn.get(assistantTurn) ?? []
        for (const record of turnRecords) used.add(record.id)
        const turnCalls = turnRecords.flatMap(calls)
        if (message.content.trim() || turnCalls.length === 0) {
          const record = turnRecords.at(-1)
          const status = turnRecords.some(item => item.status === 'running') ? 'running'
            : record?.status ?? 'completed'
          all.push({ id: `message:${message.id}`, runId, sequence: message.sequence, turn: assistantTurn,
            kind: 'assistant', summary: message.content.trim() || (status === 'failed' ? t('nexusChat.trajectory.failed') : t('nexusChat.trajectory.noResponse')),
            content: message.content, createdAt: message.created_at, status, records: turnRecords })
        }
        const uniqueCalls = new Map(turnCalls.map(call => [call.id, call]))
        let callOffset = 1
        for (const call of uniqueCalls.values()) {
          const result = resultsByCall.get(`${runId}:${call.id}`)
          all.push({ id: `tool:${runId}:${call.id}`, runId,
            sequence: result?.sequence ?? message.sequence + callOffset / 100,
            turn: assistantTurn, kind: 'tool', summary: call.name, content: '',
            createdAt: result?.created_at ?? message.created_at,
            status: result ? 'completed' : 'running', records: turnRecords,
            toolName: call.name, toolArguments: call.arguments, toolResult: result?.content })
          callOffset += 1
        }
        continue
      }
      if (message.role === 'tool' && (!message.tool_call_id || !runRecords.some(record =>
        calls(record).some(call => call.id === message.tool_call_id)))) {
        all.push({ id: `tool-result:${message.id}`, runId, sequence: message.sequence, turn: null,
          kind: 'tool', summary: t('nexusChat.trajectory.toolResult'), content: message.content,
          createdAt: message.created_at, status: 'completed', records: [], toolResult: message.content })
      }
    }
    for (const record of runRecords) {
      if (used.has(record.id)) continue
      all.push({ id: `request:${record.id}`, runId, sequence: Number.MAX_SAFE_INTEGER - runRecords.length + record.sequence,
        turn: record.turn, kind: 'assistant', summary: record.status === 'failed'
          ? (record.error_code ?? t('nexusChat.trajectory.failed')) : t('nexusChat.trajectory.modelRequest'),
        content: typeof record.response_snapshot.text === 'string' ? record.response_snapshot.text : '',
        createdAt: record.started_at, status: record.status, records: [record] })
    }
  }
  return all.sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.sequence - b.sequence)
})
const activityGroups = computed(() => {
  const byRun = new Map<string, Activity[]>()
  for (const activity of activities.value) byRun.set(activity.runId, [...(byRun.get(activity.runId) ?? []), activity])
  return [...byRun.entries()]
    .sort(([, left], [, right]) => (left[0]?.createdAt ?? '').localeCompare(right[0]?.createdAt ?? ''))
    .map(([runId, items], index) => ({
      runId,
      label: `${t('nexusChat.trajectory.runGroup', { run: index + 1 })} · ${runId.slice(0, 8)}`,
      activities: items,
    }))
})

watch(activities, items => {
  if (!items.some(item => item.id === selectedId.value)) selectedId.value = items[0]?.id ?? ''
}, { immediate: true })
const selected = computed(() => activities.value.find(item => item.id === selectedId.value) ?? null)
const totalSessionTokens = computed(() => {
  const totals = new Map<string, number>()
  for (const record of props.records) {
    if (record.run_total_tokens !== null) totals.set(record.run_id, Math.max(totals.get(record.run_id) ?? 0, record.run_total_tokens))
  }
  return [...totals.values()].reduce((sum, value) => sum + value, 0)
})
const requestCount = computed(() => props.records.length)
const cacheReadTokens = computed(() => props.records.reduce((sum, record) => sum + (record.usage.cache_read ?? 0), 0))
const inputTokens = computed(() => props.records.reduce((sum, record) => sum + (record.usage.input ?? 0), 0))
const cacheHitRate = computed(() => inputTokens.value > 0 ? Math.round(cacheReadTokens.value / inputTokens.value * 100) : null)

function formatTokens(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : new Intl.NumberFormat().format(value)
}
function activityTokens(activity: Activity): string | null {
  const usageRecords = activity.records.filter(record => typeof record.usage.input === 'number' || typeof record.usage.output === 'number')
  if (usageRecords.length) {
    const total = usageRecords.reduce((sum, record) => sum + (record.usage.input ?? 0) + (record.usage.output ?? 0), 0)
    return `${formatTokens(total)} ${t('nexusChat.trajectory.tokensActual')}`
  }
  const estimate = activity.records.reduce((sum, record) => sum + record.input_estimate_tokens, 0)
  return estimate > 0 ? `${formatTokens(estimate)} ${t('nexusChat.trajectory.tokensEstimated')}` : null
}
function activityLabel(kind: Activity['kind']): string {
  if (kind === 'user') return t('nexusChat.trajectory.activityUser')
  if (kind === 'assistant') return t('nexusChat.trajectory.activityAssistant')
  return t('nexusChat.trajectory.activityTool')
}
function duration(record: RunTrajectoryRecord): string {
  if (!record.completed_at) return '—'
  const elapsed = Math.max(0, new Date(record.completed_at).getTime() - new Date(record.started_at).getTime())
  return `${new Intl.NumberFormat().format(elapsed)} ${t('nexusChat.trajectory.milliseconds')}`
}
function details(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}
</script>

<template>
  <section class="trajectory" data-testid="chat-trajectory" :aria-label="t('nexusChat.trajectory.title')">
    <div class="trajectory__overview" aria-label="轨迹统计">
      <div class="trajectory__stat"><span>{{ t('nexusChat.trajectory.requests') }}</span><strong>{{ formatTokens(requestCount) }}</strong><small>{{ t('nexusChat.trajectory.modelRequest') }}</small></div>
      <div class="trajectory__stat"><span>{{ t('nexusChat.trajectory.totalTokens') }}</span><strong>{{ formatTokens(totalSessionTokens) }}</strong><small>{{ t('nexusChat.trajectory.sessionTotalHint') }}</small></div>
      <div class="trajectory__stat"><span>{{ t('nexusChat.trajectory.cacheHits') }}</span><strong>{{ formatTokens(cacheReadTokens) }}</strong><small>{{ cacheHitRate === null ? t('nexusChat.trajectory.cacheRateUnknown') : t('nexusChat.trajectory.cacheRate', { rate: cacheHitRate }) }}</small></div>
    </div>
    <t-alert v-if="error" theme="error" :message="t('nexusChat.trajectory.loadFailed')">
      <template #operation><t-button variant="text" @click="emit('retry')">{{ t('common.retry') }}</t-button></template>
    </t-alert>
    <t-loading :loading="loading && records.length === 0 && messages.length === 0">
      <t-empty v-if="!loading && activities.length === 0" :description="t('nexusChat.trajectory.empty')" />
      <div v-else class="trajectory__split">
        <div class="trajectory__table-scroll">
          <table class="trajectory__table">
            <colgroup><col class="trajectory__kind-column"><col><col class="trajectory__token-column"></colgroup>
            <thead><tr><th>{{ t('nexusChat.trajectory.record') }}</th><th>{{ t('nexusChat.trajectory.content') }}</th><th>{{ t('nexusChat.trajectory.tokensHeader') }}</th></tr></thead>
            <tbody v-for="group in activityGroups" :key="group.runId" :data-run-id="group.runId">
              <tr class="trajectory__run-row"><th colspan="3" :title="group.runId">{{ group.label }}</th></tr>
              <tr v-for="activity in group.activities" :key="activity.id" :aria-selected="activity.id === selectedId"
                :data-kind="activity.kind" :data-status="activity.status" tabindex="0" @click="selectedId = activity.id"
                @keydown.enter.prevent="selectedId = activity.id" @keydown.space.prevent="selectedId = activity.id">
                <td class="trajectory__kind"><strong>{{ activityLabel(activity.kind) }}</strong><small>{{ activity.turn ? t('nexusChat.trajectory.turn', { turn: activity.turn }) : activity.createdAt }}</small></td>
                <td class="trajectory__summary" :title="activity.summary"><span>{{ activity.summary }}</span></td>
                <td class="trajectory__tokens" :title="activityTokens(activity) ?? ''"><span v-if="activityTokens(activity)">{{ activityTokens(activity) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <aside v-if="selected" class="trajectory__inspector" data-testid="trajectory-inspector">
          <header><div><h2>{{ activityLabel(selected.kind) }}<template v-if="selected.toolName"> · {{ selected.toolName }}</template></h2><small>{{ selected.turn ? t('nexusChat.trajectory.turn', { turn: selected.turn }) : selected.createdAt }} · {{ selected.status }}</small></div></header>
          <template v-if="selected.kind === 'tool'">
            <details v-if="selected.toolArguments !== undefined" open><summary>{{ t('nexusChat.trajectory.toolArguments') }}</summary><pre>{{ selected.toolArguments }}</pre></details>
            <details v-if="selected.toolResult !== undefined" open><summary>{{ t('nexusChat.trajectory.toolResult') }}</summary><pre>{{ selected.toolResult }}</pre></details>
          </template>
          <template v-else>
            <details open><summary>{{ activityLabel(selected.kind) }}</summary><pre>{{ selected.content || selected.summary }}</pre></details>
            <details v-for="record in selected.records" :key="record.id" open>
              <summary>{{ t('nexusChat.trajectory.modelRequest') }} #{{ record.sequence }} · {{ record.status }}</summary>
              <div class="trajectory__metrics">
                <div><span>{{ t('nexusChat.trajectory.inputEstimate') }}</span><strong>{{ formatTokens(record.input_estimate_tokens) }}</strong></div>
                <div><span>{{ t('nexusChat.trajectory.actualUsage') }}</span><strong>{{ formatTokens(record.usage.input) }} / {{ formatTokens(record.usage.output) }}</strong></div>
                <div><span>{{ t('nexusChat.trajectory.runTotal') }}</span><strong>{{ formatTokens(record.run_total_tokens) }}</strong></div>
                <div><span>{{ t('nexusChat.trajectory.duration') }}</span><strong>{{ duration(record) }}</strong></div>
              </div>
              <details><summary>{{ t('nexusChat.trajectory.request') }}</summary>
                <section v-for="(message, index) in (record.request_snapshot.messages as Record<string, unknown>[])" :key="index" class="trajectory__message">
                  <strong>{{ String(message.role ?? '') }}</strong><pre>{{ details(message.content ?? '') }}</pre>
                </section>
              </details>
              <details v-if="Array.isArray(record.request_snapshot.tools)"><summary>{{ t('nexusChat.trajectory.tools') }} ({{ (record.request_snapshot.tools as unknown[]).length }})</summary><pre>{{ details(record.request_snapshot.tools) }}</pre></details>
              <details><summary>{{ t('nexusChat.trajectory.response') }}</summary><pre>{{ details(record.response_snapshot) }}</pre><p v-if="record.error_code" class="trajectory__error">{{ record.error_code }}</p></details>
            </details>
          </template>
        </aside>
      </div>
    </t-loading>
  </section>
</template>

<style scoped>
.trajectory { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; padding: 14px 18px; box-sizing: border-box; }
.trajectory__overview { display: grid; flex: 0 0 auto; grid-template-columns: repeat(3, minmax(120px, 168px)); gap: 10px; }
.trajectory__stat { display: flex; min-height: 76px; flex-direction: column; justify-content: center; gap: 3px; padding: 9px 12px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); box-shadow: var(--app-shadow-sm); }
.trajectory__stat span, .trajectory__stat small, .trajectory__table small, .trajectory__inspector header small { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.trajectory__stat strong { font-size: var(--app-text-lg); line-height: 1.2; font-variant-numeric: tabular-nums; }
.trajectory__split { display: grid; flex: 1; min-height: 0; grid-template-columns: minmax(320px, 1.2fr) minmax(320px, 1fr); overflow: hidden; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); }
.trajectory__table-scroll { min-width: 0; overflow: auto; border-right: 1px solid var(--td-component-stroke); }
.trajectory__table { width: 100%; table-layout: fixed; border-collapse: collapse; text-align: left; font-size: var(--app-text-sm); }
.trajectory__kind-column { width: 104px; }
.trajectory__token-column { width: 88px; }
.trajectory__table th { position: sticky; top: 0; z-index: 1; padding: 9px 10px; background: var(--td-bg-color-secondarycontainer); color: var(--td-text-color-secondary); font-weight: 500; }
.trajectory__table td { max-width: 360px; padding: 10px; border-top: 1px solid var(--td-component-stroke); vertical-align: top; }
.trajectory__table .trajectory__run-row th { position: static; padding: 8px 10px; border-top: 1px solid var(--td-component-stroke); background: var(--td-bg-color-container); color: var(--td-text-color-primary); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trajectory__table tbody tr { cursor: pointer; }
.trajectory__table tbody tr.trajectory__run-row { cursor: default; }
.trajectory__table tbody tr:hover { background: var(--td-bg-color-container-hover); }
.trajectory__table tbody tr.trajectory__run-row:hover { background: var(--td-bg-color-container); }
.trajectory__table tbody tr[aria-selected="true"] { background: var(--td-brand-color-light); }
.trajectory__table tbody tr:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; }
.trajectory__table .trajectory__kind strong, .trajectory__table .trajectory__kind small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trajectory__table .trajectory__kind small { margin-top: 4px; }
.trajectory__summary, .trajectory__tokens { overflow: hidden; }
.trajectory__summary span, .trajectory__tokens span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trajectory__tokens { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); font-variant-numeric: tabular-nums; }
.trajectory__inspector { min-width: 0; overflow: auto; padding: 14px; }
.trajectory__inspector header h2 { margin: 0 0 3px; font-size: var(--app-text-md); }
.trajectory__metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 12px 0; }
.trajectory__metrics div { display: grid; gap: 3px; min-width: 0; padding: 8px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); }
.trajectory__metrics span { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.trajectory__metrics strong { overflow-wrap: anywhere; font-size: var(--app-text-sm); font-variant-numeric: tabular-nums; }
.trajectory__inspector details { margin-top: 10px; border-top: 1px solid var(--td-component-stroke); }
.trajectory__inspector summary { padding: 9px 0; cursor: pointer; font-weight: 600; }
.trajectory__message { margin: 7px 0; padding: 8px; border-radius: var(--app-radius-sm); background: var(--td-bg-color-secondarycontainer); }
.trajectory pre { overflow: auto; max-height: 36vh; margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.55 var(--app-font-mono); }
.trajectory__error { color: var(--td-error-color); }
@media (max-width: 900px) { .trajectory { overflow: auto; } .trajectory__overview { grid-template-columns: repeat(3, minmax(92px, 1fr)); } .trajectory__split { min-height: 560px; grid-template-columns: minmax(260px, 1fr); grid-template-rows: minmax(240px, 0.8fr) minmax(280px, 1fr); } .trajectory__table-scroll { border-right: 0; border-bottom: 1px solid var(--td-component-stroke); } }
</style>
