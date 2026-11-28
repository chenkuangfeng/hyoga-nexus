<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ConversationMessage, RunTrajectoryRecord } from '@nexus-web/core/api/native-runs'
import { toolDisplayName } from '@nexus-web/core/utils/toolPresentation'
import { formatMessageTimestamp } from '@/utils/messageTimestamp'

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
  kind: 'user' | 'assistant' | 'tool' | 'memory'
  memorySource?: 'default_context' | 'auto_recall'
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
const { t, te } = useI18n()
const selectedId = ref('')
const collapsedGroups = ref(new Set<string>())
const inspectorTab = ref('activity')

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
    const used = new Set<string>()
    const memorySources = new Map<'default_context' | 'auto_recall', { blocks: string[]; record: RunTrajectoryRecord }>()
    const orderedMessages = runMessages.slice().sort((a, b) => a.sequence - b.sequence)
    const recordsForCall = new Map<string, RunTrajectoryRecord>()
    for (const record of runRecords) for (const call of calls(record)) recordsForCall.set(call.id, record)
    for (const message of orderedMessages) {
      if (message.role === 'user') {
        all.push({ id: `message:${message.id}`, runId, sequence: message.sequence, turn: null,
          kind: 'user', summary: message.content, content: message.content, createdAt: message.created_at,
          status: 'completed', records: [] })
      } else if (message.role === 'assistant' && message.content.trim()) {
        const matched = runRecords.find(record => !used.has(record.id) && record.response_snapshot.text === message.content)
        if (matched) used.add(matched.id)
        const messageRecords = matched ? [matched] : []
        all.push({ id: `message:${message.id}`, runId, sequence: message.sequence, turn: matched?.turn ?? null,
          kind: 'assistant', summary: message.content, content: message.content, createdAt: message.created_at,
          status: matched?.status ?? 'completed', records: messageRecords })
      }
    }
    // Tool rows come from each actual model response, keyed by call id rather than turn-number alignment.
    // This remains correct when a Run resumes with a non-zero persisted turn counter.
    const callActivities = new Map<string, Activity>()
    for (const record of runRecords) {
      for (const call of calls(record)) {
        const result = resultsByCall.get(`${runId}:${call.id}`)
        callActivities.set(call.id, { id: `tool:${runId}:${call.id}`, runId,
          sequence: result?.sequence ?? record.sequence + call.id.length / 1000, turn: record.turn,
          kind: 'tool', summary: call.name, content: '', createdAt: result?.created_at ?? record.started_at,
          status: result ? 'completed' : record.status === 'completed' ? 'running' : record.status,
          records: [record], toolName: call.name, toolArguments: call.arguments, toolResult: result?.content })
      }
      const requestMessages = record.request_snapshot.messages as Array<Record<string, unknown>> | undefined
      for (const message of requestMessages ?? []) {
        if (typeof message.content !== 'string') continue
        const blocks = message.content.match(/<user_memory\b[^>]*>[\s\S]*?<\/user_memory>/g) ?? []
        for (const block of blocks) {
          const source = /<user_memory\s+kind="resident"/.test(block) ? 'default_context' : 'auto_recall'
          const current = memorySources.get(source)
          if (current?.blocks.includes(block)) continue
          if (current) current.blocks.push(block)
          else memorySources.set(source, { blocks: [block], record })
        }
      }
    }
    for (const [source, memory] of memorySources) {
      const runInput = orderedMessages.find(message => message.role === 'user')
      const count = memory.blocks.reduce((total, block) => {
        const entries = block.match(/^-\s+/gm)?.length ?? 0
        return total + Math.max(entries, 1)
      }, 0)
      all.push({ id: `memory:${source}:${runId}`, runId, sequence: runInput ? runInput.sequence + 0.1 : memory.record.sequence - 0.5,
        turn: memory.record.turn, kind: 'memory', memorySource: source,
        summary: `${source === 'default_context' ? t('nexusMemory.defaultContextIncluded') : t('nexusMemory.autoRecallUsed')} · ${t('nexusChat.trajectory.memoryUsedCount', { count })}`,
        content: memory.blocks.join('\n\n'),
        createdAt: runInput?.created_at ?? memory.record.started_at, status: 'completed',
        // This row describes context provenance. The memory text was included in a model
        // request, but it is not itself a model request; keep the request snapshot on the
        // assistant activity where it belongs.
        records: [] })
    }
    all.push(...callActivities.values())
    for (const message of orderedMessages) {
      if (message.role === 'tool' && (!message.tool_call_id || !recordsForCall.has(message.tool_call_id))) {
        all.push({ id: `tool-result:${message.id}`, runId, sequence: message.sequence, turn: null,
          kind: 'tool', summary: t('nexusChat.trajectory.toolResult'), content: message.content,
          createdAt: message.created_at, status: 'completed', records: [], toolResult: message.content })
      }
    }
    for (const record of runRecords) {
      const responseText = typeof record.response_snapshot.text === 'string' ? record.response_snapshot.text : ''
      if (used.has(record.id) || (calls(record).length && record.status === 'completed')) continue
      all.push({ id: `request:${record.id}`, runId, sequence: record.sequence - 0.25,
        turn: record.turn, kind: 'assistant', summary: record.status === 'failed'
          ? (record.error_code ?? t('nexusChat.trajectory.failed')) : responseText || t('nexusChat.trajectory.modelRequest'),
        content: responseText, createdAt: record.started_at, status: record.status, records: [record] })
    }
  }
  return all.sort((a, b) => b.createdAt.localeCompare(a.createdAt) || b.sequence - a.sequence)
})
const activityGroups = computed(() => {
  const byRun = new Map<string, Activity[]>()
  for (const activity of activities.value) byRun.set(activity.runId, [...(byRun.get(activity.runId) ?? []), activity])
  return [...byRun.entries()]
    .sort(([, left], [, right]) => (right[0]?.createdAt ?? '').localeCompare(left[0]?.createdAt ?? ''))
    .map(([runId, unsortedItems]) => {
      const items = unsortedItems.slice().sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.sequence - b.sequence)
      const groups = items.reduce<Array<{ id: string; user: Activity | null; activities: Activity[] }>>((result, activity) => {
        if (activity.kind === 'user') {
          result.push({ id: activity.id, user: activity, activities: [] })
        } else {
          if (result.length === 0) result.push({ id: `run:${runId}:leading`, user: null, activities: [] })
          result[result.length - 1]?.activities.push(activity)
        }
        return result
      }, [])
      // Keep the newest user-input group first, while preserving chronological steps within each group.
      return { runId, groups: groups.reverse() }
    })
})

watch(activities, items => {
  if (!items.some(item => item.id === selectedId.value)) selectedId.value = ''
}, { immediate: true })
const selected = computed(() => activities.value.find(item => item.id === selectedId.value) ?? null)
const inspectorRecords = computed(() => (selected.value?.records ?? []).slice().sort((a, b) => b.sequence - a.sequence))
const inspectorTools = computed(() => {
  const activity = selected.value
  return activity?.kind === 'tool' ? [activity] : []
})
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
  if (activity.kind === 'tool' || activity.kind === 'user') return null
  if (activity.kind === 'memory') {
    const estimate = Math.ceil(activity.content.length / 3)
    return `${formatTokens(estimate)} ${t('nexusChat.trajectory.tokensEstimated')}`
  }
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
  if (kind === 'memory') return t('nexusChat.trajectory.memoryRecall')
  return t('nexusChat.trajectory.activityTool')
}
function displayTool(name: string): string {
  return toolDisplayName(name, key => t(key), te)
}
function toggleGroup(id: string): void {
  const next = new Set(collapsedGroups.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedGroups.value = next
}
function selectActivity(activity: Activity): void {
  selectedId.value = activity.id
  inspectorTab.value = activity.kind === 'tool' ? 'tools' : 'activity'
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
      <div v-else class="trajectory__split" :class="{ 'trajectory__split--inspector': !!selected }">
        <div class="trajectory__table-scroll">
          <table class="trajectory__table">
            <colgroup><col class="trajectory__kind-column"><col><col class="trajectory__time-column"><col class="trajectory__token-column"></colgroup>
            <thead><tr><th>{{ t('nexusChat.trajectory.record') }}</th><th>{{ t('nexusChat.trajectory.content') }}</th><th>{{ t('nexusChat.trajectory.timeHeader') }}</th><th>{{ t('nexusChat.trajectory.tokensHeader') }}</th></tr></thead>
            <tbody v-for="group in activityGroups" :key="group.runId" :data-run-id="group.runId">
              <template v-for="inputGroup in group.groups" :key="inputGroup.id">
                <tr v-if="inputGroup.user" class="trajectory__input-row"
                  :class="{ 'trajectory__input-row--run-start': inputGroup === group.groups[0] }"
                  :aria-selected="inputGroup.user.id === selectedId"
                  :aria-expanded="!collapsedGroups.has(inputGroup.id)" tabindex="0"
                  @click="selectActivity(inputGroup.user); toggleGroup(inputGroup.id)"
                  @keydown.enter.prevent="selectActivity(inputGroup.user); toggleGroup(inputGroup.id)"
                  @keydown.space.prevent="selectActivity(inputGroup.user); toggleGroup(inputGroup.id)">
                  <td class="trajectory__kind" :title="inputGroup.user.createdAt"><strong><span class="trajectory__chevron" :class="{ 'trajectory__chevron--collapsed': collapsedGroups.has(inputGroup.id) }" aria-hidden="true"></span>{{ activityLabel('user') }}</strong></td>
                  <td class="trajectory__summary" :title="inputGroup.user.summary"><span>{{ inputGroup.user.summary }}</span></td>
                  <td class="trajectory__time" :title="inputGroup.user.createdAt">{{ formatMessageTimestamp(inputGroup.user.createdAt) || '—' }}</td>
                  <td class="trajectory__tokens"></td>
                </tr>
                <tr v-for="activity in inputGroup.activities" v-show="!collapsedGroups.has(inputGroup.id)"
                  :key="activity.id" class="trajectory__activity-row" :aria-selected="activity.id === selectedId"
                  :data-kind="activity.kind" :data-status="activity.status" tabindex="0"
                  @click="selectActivity(activity)" @keydown.enter.prevent="selectActivity(activity)"
                  @keydown.space.prevent="selectActivity(activity)">
                  <td class="trajectory__kind" :title="activity.turn ? t('nexusChat.trajectory.turn', { turn: activity.turn }) : activity.createdAt"><strong>{{ activityLabel(activity.kind) }}</strong></td>
                  <td class="trajectory__summary" :title="activity.summary"><span>{{ activity.kind === 'tool' && activity.toolName ? displayTool(activity.toolName) : activity.summary }}</span></td>
                  <td class="trajectory__time" :title="activity.createdAt">{{ formatMessageTimestamp(activity.createdAt) || '—' }}</td>
                  <td class="trajectory__tokens" :title="activityTokens(activity) ?? ''"><span v-if="activityTokens(activity)">{{ activityTokens(activity) }}</span></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <aside v-if="selected" class="trajectory__inspector" data-testid="trajectory-inspector">
          <header><div><h2>{{ activityLabel(selected.kind) }}<template v-if="selected.toolName"> · {{ displayTool(selected.toolName) }}</template></h2><small>{{ selected.turn ? t('nexusChat.trajectory.turn', { turn: selected.turn }) : selected.createdAt }} · {{ selected.status }}</small></div></header>
          <t-tabs v-model="inspectorTab" class="trajectory__inspector-tabs">
            <t-tab-panel value="activity" :label="t('nexusChat.trajectory.details')">
              <section class="trajectory__detail-section"><h3>{{ activityLabel(selected.kind) }}</h3><pre>{{ selected.content || selected.summary }}</pre></section>
            </t-tab-panel>
            <t-tab-panel v-if="inspectorTools.length" value="tools" :label="`${t('nexusChat.trajectory.toolList')} (${inspectorTools.length})`">
              <section v-for="activity in inspectorTools" :key="activity.id" class="trajectory__detail-section trajectory__tool-item">
                <h3>{{ displayTool(activity.toolName ?? activity.summary) }}</h3>
                <p v-if="activity.toolArguments !== undefined"><strong>{{ t('nexusChat.trajectory.toolArguments') }}</strong><pre>{{ activity.toolArguments }}</pre></p>
                <p v-if="activity.toolResult !== undefined"><strong>{{ t('nexusChat.trajectory.toolResult') }}</strong><pre>{{ activity.toolResult }}</pre></p>
                <p v-if="activity.toolResult === undefined" class="trajectory__pending">{{ activity.status }}</p>
              </section>
              <p v-if="inspectorTools.length === 0" class="trajectory__empty">—</p>
            </t-tab-panel>
            <t-tab-panel v-if="inspectorRecords.length" value="requests" :label="`${t('nexusChat.trajectory.modelRequest')} (${inspectorRecords.length})`">
              <section v-for="record in inspectorRecords" :key="record.id" class="trajectory__detail-section trajectory__request-item" :data-request-sequence="record.sequence">
              <h3>{{ t('nexusChat.trajectory.modelRequest') }} #{{ record.sequence }} · {{ record.status }}</h3>
              <div class="trajectory__metrics">
                <div><span>{{ t('nexusChat.trajectory.inputEstimate') }}</span><strong>{{ formatTokens(record.input_estimate_tokens) }}</strong></div>
                <div><span>{{ t('nexusChat.trajectory.actualUsage') }}</span><strong>{{ formatTokens(record.usage.input) }} / {{ formatTokens(record.usage.output) }}</strong></div>
                <div><span>{{ t('nexusChat.trajectory.runTotal') }}</span><strong>{{ formatTokens(record.run_total_tokens) }}</strong></div>
                <div><span>{{ t('nexusChat.trajectory.duration') }}</span><strong>{{ duration(record) }}</strong></div>
              </div>
              <section class="trajectory__snapshot"><h4>{{ t('nexusChat.trajectory.request') }}</h4>
                <section v-for="(message, index) in (record.request_snapshot.messages as Record<string, unknown>[])" :key="index" class="trajectory__message">
                  <strong>{{ String(message.role ?? '') }}</strong><pre>{{ details(message.content ?? '') }}</pre>
                </section>
              </section>
              <section v-if="Array.isArray(record.request_snapshot.tools)" class="trajectory__snapshot"><h4>{{ t('nexusChat.trajectory.tools') }} ({{ (record.request_snapshot.tools as unknown[]).length }})</h4><pre>{{ details(record.request_snapshot.tools) }}</pre></section>
              <section class="trajectory__snapshot"><h4>{{ t('nexusChat.trajectory.response') }}</h4><pre>{{ details(record.response_snapshot) }}</pre><p v-if="record.error_code" class="trajectory__error">{{ record.error_code }}</p></section>
              </section>
            </t-tab-panel>
          </t-tabs>
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
.trajectory__split { display: grid; flex: 1; min-height: 0; grid-template-columns: minmax(0, 1fr); overflow: hidden; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); }
.trajectory__split--inspector { grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr); }
.trajectory__table-scroll { height: 100%; min-width: 0; min-height: 0; overflow: auto; border-right: 1px solid var(--td-component-stroke); }
.trajectory__table { width: 100%; table-layout: fixed; border-collapse: collapse; text-align: left; font-size: var(--app-text-sm); }
.trajectory__kind-column { width: 104px; }
.trajectory__time-column { width: 136px; }
.trajectory__token-column { width: 88px; }
.trajectory__table th { position: sticky; top: 0; z-index: 1; padding: 7px 8px; background: var(--td-bg-color-secondarycontainer); color: var(--td-text-color-secondary); font-weight: 550; font-size: 13px; line-height: 16px; }
.trajectory__table td { height: 30px; max-width: 0; box-sizing: border-box; padding: 0 8px; border-top: 1px solid var(--td-component-stroke); vertical-align: middle; line-height: 28px; }
.trajectory__table tbody tr { cursor: pointer; }
.trajectory__table tbody tr:hover { background: var(--td-bg-color-container-hover); }
.trajectory__table tbody tr[aria-selected="true"] { background: var(--td-brand-color-light); }
.trajectory__table tbody tr:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; }
.trajectory__table .trajectory__input-row td { background: var(--td-bg-color-secondarycontainer); font-weight: 600; }
.trajectory__table .trajectory__input-row[aria-selected="true"] td { background: var(--td-brand-color-light); }
.trajectory__table .trajectory__input-row td:first-child { border-left: 1px solid var(--td-component-stroke); }
.trajectory__table .trajectory__input-row--run-start td { box-shadow: inset 0 1px 0 var(--td-component-stroke); }
.trajectory__table .trajectory__activity-row td:first-child { border-left: 1px solid var(--td-component-stroke); padding-left: 19px; }
.trajectory__table .trajectory__activity-row .trajectory__summary { padding-left: 18px; }
.trajectory__table .trajectory__kind strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 500; }
.trajectory__table .trajectory__input-row .trajectory__kind strong { font-weight: 650; }
.trajectory__chevron { display: inline-block; width: 7px; height: 7px; margin: 0 9px 2px 2px; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; color: var(--td-brand-color); transform: rotate(45deg); transition: transform 120ms ease; }
.trajectory__chevron--collapsed { transform: rotate(-45deg); }
.trajectory__summary, .trajectory__tokens { overflow: hidden; }
.trajectory__time { overflow: hidden; color: var(--td-text-color-secondary); font-size: 11px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.trajectory__summary span, .trajectory__tokens span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 14px; }
.trajectory__summary span { font-size: 12px; }
.trajectory__tokens { color: var(--td-text-color-secondary); font-size: 11px; font-variant-numeric: tabular-nums; }
.trajectory__inspector { min-width: 0; overflow: auto; padding: 14px; }
.trajectory__inspector-tabs { min-height: 0; }
.trajectory__inspector header h2 { margin: 0 0 3px; font-size: var(--app-text-md); }
.trajectory__metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 12px 0; }
.trajectory__metrics div { display: grid; gap: 3px; min-width: 0; padding: 8px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); }
.trajectory__metrics span { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.trajectory__metrics strong { overflow-wrap: anywhere; font-size: var(--app-text-sm); font-variant-numeric: tabular-nums; }
.trajectory__detail-section { margin-top: 8px; padding-top: 10px; border-top: 1px solid var(--td-component-stroke); }
.trajectory__detail-section h3 { margin: 0 0 8px; font-size: var(--app-text-sm); font-weight: 600; }
.trajectory__snapshot { margin-top: 10px; }
.trajectory__snapshot h4 { margin: 0 0 6px; font-size: var(--app-text-xs); font-weight: 600; color: var(--td-text-color-secondary); }
.trajectory__tool-item p { margin: 6px 0 10px; }
.trajectory__tool-item p strong { font-size: var(--app-text-xs); }
.trajectory__pending, .trajectory__empty { color: var(--td-text-color-secondary); }
.trajectory__message { margin: 7px 0; padding: 8px; border-radius: var(--app-radius-sm); background: var(--td-bg-color-secondarycontainer); }
.trajectory pre { overflow: auto; max-height: 36vh; margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.55 var(--app-font-mono); }
.trajectory__error { color: var(--td-error-color); }
@media (max-width: 900px) { .trajectory { overflow: auto; } .trajectory__overview { grid-template-columns: repeat(3, minmax(92px, 1fr)); } .trajectory__split--inspector { min-height: 560px; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(240px, 0.8fr) minmax(280px, 1fr); } .trajectory__table-scroll { border-right: 0; border-bottom: 1px solid var(--td-component-stroke); } }
</style>
