<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RunEvent } from '@nexus-web/core/api/native-runs'

const props = defineProps<{ eventsByRun: ReadonlyMap<string, readonly RunEvent[]>; liveRunId: string | null; liveEvents: readonly RunEvent[] }>()
const { t } = useI18n()
type Trace = { runId: string; event: RunEvent }
const traces = computed<Trace[]>(() => {
  const runs = new Map(props.eventsByRun)
  if (props.liveRunId) runs.set(props.liveRunId, props.liveEvents)
  return [...runs.entries()].flatMap(([runId, events]) => events.map(event => ({ runId, event })))
    .sort((a, b) => a.event.occurred_at.localeCompare(b.event.occurred_at) || a.event.sequence - b.event.sequence)
})
const modelEvents = computed(() => traces.value.filter(({ event }) => event.event_type === 'model.completed'))
function hasUsage(event: RunEvent): boolean {
  const usage = record(event.payload.usage)
  return number(usage.input) !== null || number(usage.output) !== null
}
const actualUsage = computed(() => modelEvents.value.reduce((sum, { event }) => {
  const usage = record(event.payload.usage)
  return sum + (number(usage.input) ?? 0) + (number(usage.output) ?? 0)
}, 0))
const actualCalls = computed(() => modelEvents.value.filter(({ event }) => hasUsage(event)).length)
const latestRunTotal = computed(() => {
  const totals = new Map<string, number>()
  for (const { runId, event } of modelEvents.value) {
    const total = number(event.payload.run_total_tokens) ?? number(event.payload.tokens)
    if (total !== null) totals.set(runId, total)
  }
  return [...totals.values()].reduce((sum, value) => sum + value, 0)
})
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function number(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null }
function label(event: RunEvent): string {
  const keys: Record<string, string> = {
    'run.started': 'runStarted', 'run.completed': 'runCompleted', 'run.failed': 'runFailed', 'run.cancelled': 'runCancelled',
    'turn.started': 'turnStarted', 'model.started': 'modelStarted', 'model.completed': 'modelCompleted', 'model.recovery': 'modelRecovery',
    'context.compacted': 'contextCompacted', 'tool.started': 'toolStarted', 'tool.completed': 'toolCompleted', 'tool.failed': 'toolFailed', 'tool.progress': 'toolProgress',
    'approval.requested': 'approvalRequested', 'approval.resolved': 'approvalResolved', 'input.requested': 'inputRequested',
  }
  const key = keys[event.event_type]
  return key ? t(`nexusChat.trajectory.events.${key}`) : event.event_type
}
function detail(event: RunEvent): string {
  const p = event.payload
  const name = typeof p.tool_name === 'string' ? p.tool_name : typeof p.name === 'string' ? p.name : ''
  const turn = number(p.turn)
  const summary = typeof p.summary === 'string' ? p.summary : typeof p.text === 'string' ? p.text : ''
  const code = typeof p.error_code === 'string' ? p.error_code : ''
  return [name, turn === null ? '' : `第 ${turn} 轮`, typeof p.strategy === 'string' ? p.strategy : '', code, summary].filter(Boolean).join(' · ')
}
function tokens(value: unknown): string { const n = number(value); return n === null ? '—' : new Intl.NumberFormat().format(n) }
function usageText(event: RunEvent): string {
  const usage = record(event.payload.usage)
  const input = number(usage.input), output = number(usage.output)
  return input === null && output === null ? t('nexusChat.trajectory.usageUnavailable') : `${t('nexusChat.trajectory.actualUsage')} ${tokens(input)} / ${tokens(output)}`
}
</script>

<template>
  <section class="trajectory" data-testid="chat-trajectory" :aria-label="t('nexusChat.trajectory.title')">
    <div class="trajectory__summary">
      <div><span>{{ t('nexusChat.trajectory.totalSession') }}</span><strong>{{ tokens(latestRunTotal) }}</strong></div>
      <div><span>{{ t('nexusChat.trajectory.actualTotal') }}</span><strong>{{ tokens(actualUsage) }}</strong><small>{{ t('nexusChat.trajectory.callsWithUsage', { count: actualCalls }) }}</small></div>
    </div>
    <t-empty v-if="traces.length === 0" :description="t('nexusChat.trajectory.empty')" />
    <ol v-else class="trajectory__list">
      <li v-for="{ runId, event } in traces" :key="`${runId}:${event.sequence}:${event.event_id}`" class="trajectory__event">
        <span class="trajectory__dot" aria-hidden="true" />
        <div class="trajectory__body">
          <div class="trajectory__heading"><strong>{{ label(event) }}</strong><time>{{ new Date(event.occurred_at).toLocaleString() }}</time></div>
          <p v-if="detail(event)">{{ detail(event) }}</p>
          <div v-if="event.event_type === 'model.started'" class="trajectory__usage">{{ t('nexusChat.trajectory.inputEstimate') }} {{ tokens(event.payload.input_estimate_tokens) }}</div>
          <div v-if="event.event_type === 'model.completed'" class="trajectory__usage">
            <span>{{ usageText(event) }}</span><span>{{ t('nexusChat.trajectory.requestEstimate') }} {{ tokens(event.payload.request_input_estimate_tokens) }}</span>
            <span>{{ t('nexusChat.trajectory.runTotal') }} {{ tokens(event.payload.run_total_tokens ?? event.payload.tokens) }}</span>
          </div>
          <details v-if="event.event_type.endsWith('.failed') || event.event_type === 'context.recovery_failed'">
            <summary>{{ t('nexusChat.trajectory.details') }}</summary><pre>{{ JSON.stringify(event.payload, null, 2) }}</pre>
          </details>
          <small>{{ runId.slice(0, 8) }} · #{{ event.sequence }}</small>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.trajectory { height: 100%; overflow: auto; padding: 20px clamp(16px, 4vw, 48px); box-sizing: border-box; }
.trajectory__summary { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 auto 20px; max-width: 900px; }
.trajectory__summary > div { display: grid; gap: 4px; min-width: 170px; padding: 14px 18px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); }
.trajectory__summary span, .trajectory__summary small, .trajectory__event small { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.trajectory__summary strong { font-size: 22px; font-variant-numeric: tabular-nums; }
.trajectory__list { list-style: none; max-width: 900px; margin: 0 auto; padding: 0 0 24px 4px; }
.trajectory__event { position: relative; display: flex; gap: 14px; padding: 0 0 18px; }
.trajectory__event:not(:last-child)::before { position: absolute; top: 12px; bottom: -2px; left: 5px; border-left: 1px solid var(--td-component-stroke); content: ''; }
.trajectory__dot { z-index: 1; flex: 0 0 10px; width: 10px; height: 10px; margin-top: 5px; border-radius: 50%; background: var(--td-brand-color); }
.trajectory__body { flex: 1; min-width: 0; padding: 12px 14px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); }
.trajectory__heading, .trajectory__usage { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px; }
.trajectory__heading { justify-content: space-between; }
.trajectory__heading time { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.trajectory__body p { margin: 6px 0; color: var(--td-text-color-secondary); }
.trajectory__usage { margin: 8px 0; font-size: var(--app-text-xs); font-variant-numeric: tabular-nums; }
.trajectory__body pre { overflow: auto; max-height: 240px; }
</style>
