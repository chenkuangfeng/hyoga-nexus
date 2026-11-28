<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RunTrajectoryRecord } from '@nexus-web/core/api/native-runs'

const props = defineProps<{
  records: readonly RunTrajectoryRecord[]
  loading: boolean
  error: boolean
}>()
const emit = defineEmits<{ retry: [] }>()
const { t } = useI18n()
const selectedId = ref('')
watch(() => props.records, records => {
  if (!records.some(record => record.id === selectedId.value)) selectedId.value = records[0]?.id ?? ''
}, { immediate: true })
const selected = computed(() => props.records.find(record => record.id === selectedId.value) ?? null)
const totalActualTokens = computed(() => props.records.reduce((sum, record) =>
  sum + (record.usage.input ?? 0) + (record.usage.output ?? 0), 0))
const callsWithUsage = computed(() => props.records.filter(record =>
  typeof record.usage.input === 'number' || typeof record.usage.output === 'number').length)
const sessionTotalTokens = computed(() => {
  const totals = new Map<string, number>()
  for (const record of props.records) {
    if (record.run_total_tokens !== null) {
      totals.set(record.run_id, Math.max(totals.get(record.run_id) ?? 0, record.run_total_tokens))
    }
  }
  return [...totals.values()].reduce((sum, value) => sum + value, 0)
})
function formatTokens(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : new Intl.NumberFormat().format(value)
}
function actualTokens(record: RunTrajectoryRecord): string {
  if (typeof record.usage.input !== 'number' && typeof record.usage.output !== 'number') return t('nexusChat.trajectory.usageUnavailable')
  return `${t('nexusChat.trajectory.inputShort')} ${formatTokens(record.usage.input)} · ${t('nexusChat.trajectory.outputShort')} ${formatTokens(record.usage.output)}`
}
function recordSummary(record: RunTrajectoryRecord): string {
  const text = record.response_snapshot.text
  if (typeof text === 'string' && text.trim()) return text.trim().replace(/\s+/g, ' ').slice(0, 240)
  const calls = record.response_snapshot.tool_calls
  if (Array.isArray(calls)) {
    const names = calls.map(call => call && typeof call === 'object' && 'name' in call ? String(call.name) : '').filter(Boolean)
    if (names.length) return names.join(', ')
  }
  return record.status === 'failed' ? (record.error_code ?? t('nexusChat.trajectory.failed')) : t('nexusChat.trajectory.noResponse')
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
    <div class="trajectory__overview">
      <div><span>{{ t('nexusChat.trajectory.requests') }}</span><strong>{{ records.length }}</strong></div>
      <div><span>{{ t('nexusChat.trajectory.totalSession') }}</span><strong>{{ formatTokens(sessionTotalTokens) }}</strong></div>
      <div><span>{{ t('nexusChat.trajectory.actualTotal') }}</span><strong>{{ formatTokens(totalActualTokens) }}</strong><small>{{ t('nexusChat.trajectory.callsWithUsage', { count: callsWithUsage }) }}</small></div>
    </div>
    <t-alert v-if="error" theme="error" :message="t('nexusChat.trajectory.loadFailed')">
      <template #operation><t-button variant="text" @click="emit('retry')">{{ t('common.retry') }}</t-button></template>
    </t-alert>
    <t-loading :loading="loading && records.length === 0">
      <t-empty v-if="!loading && records.length === 0" :description="t('nexusChat.trajectory.empty')" />
      <div v-else class="trajectory__split">
        <div class="trajectory__table-scroll">
          <table class="trajectory__table">
            <thead><tr><th>{{ t('nexusChat.trajectory.record') }}</th><th>{{ t('nexusChat.trajectory.content') }}</th></tr></thead>
            <tbody>
              <tr v-for="record in records" :key="record.id" :aria-selected="record.id === selectedId"
                :data-status="record.status" tabindex="0" @click="selectedId = record.id"
                @keydown.enter.prevent="selectedId = record.id" @keydown.space.prevent="selectedId = record.id">
                <td><strong>#{{ record.sequence }} · {{ t('nexusChat.trajectory.modelRequest') }}</strong><small>{{ t('nexusChat.trajectory.turnAttempt', { turn: record.turn, attempt: record.attempt }) }}</small></td>
                <td class="trajectory__summary" :title="recordSummary(record)">
                  <span>{{ recordSummary(record) }}</span>
                  <small>{{ t('nexusChat.trajectory.inputEstimateShort') }} {{ formatTokens(record.input_estimate_tokens) }} · {{ actualTokens(record) }}</small>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <aside v-if="selected" class="trajectory__inspector" data-testid="trajectory-inspector">
          <header><div><h2>{{ t('nexusChat.trajectory.modelRequest') }} #{{ selected.sequence }}</h2><small>{{ t('nexusChat.trajectory.turnAttempt', { turn: selected.turn, attempt: selected.attempt }) }} · {{ selected.status }}</small></div></header>
          <div class="trajectory__metrics">
            <div><span>{{ t('nexusChat.trajectory.inputEstimate') }}</span><strong>{{ formatTokens(selected.input_estimate_tokens) }}</strong></div>
            <div><span>{{ t('nexusChat.trajectory.actualUsage') }}</span><strong>{{ actualTokens(selected) }}</strong></div>
            <div><span>{{ t('nexusChat.trajectory.runTotal') }}</span><strong>{{ formatTokens(selected.run_total_tokens) }}</strong></div>
            <div><span>{{ t('nexusChat.trajectory.duration') }}</span><strong>{{ duration(selected) }}</strong></div>
          </div>
          <details open><summary>{{ t('nexusChat.trajectory.request') }}</summary>
            <section v-for="(message, index) in (selected.request_snapshot.messages as Record<string, unknown>[])" :key="index" class="trajectory__message">
              <strong>{{ String(message.role ?? '') }}</strong>
              <pre>{{ details(message.content ?? '') }}</pre>
              <pre v-if="Array.isArray(message.tool_calls) && message.tool_calls.length">{{ details(message.tool_calls) }}</pre>
            </section>
          </details>
          <details v-if="Array.isArray(selected.request_snapshot.tools)" open><summary>{{ t('nexusChat.trajectory.tools') }} ({{ (selected.request_snapshot.tools as unknown[]).length }})</summary>
            <pre>{{ details(selected.request_snapshot.tools) }}</pre>
          </details>
          <details open><summary>{{ t('nexusChat.trajectory.response') }}</summary>
            <pre>{{ typeof selected.response_snapshot.text === 'string' ? selected.response_snapshot.text : t('nexusChat.trajectory.noResponse') }}</pre>
            <pre v-if="selected.response_snapshot.tool_calls">{{ details(selected.response_snapshot.tool_calls) }}</pre>
            <p v-if="selected.error_code" class="trajectory__error">{{ selected.error_code }}</p>
          </details>
        </aside>
      </div>
    </t-loading>
  </section>
</template>

<style scoped>
.trajectory { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; padding: 14px 18px; box-sizing: border-box; }
.trajectory__overview { display: flex; flex: 0 0 auto; flex-wrap: wrap; gap: 8px; }
.trajectory__overview > div { display: flex; align-items: baseline; gap: 8px; padding: 6px 10px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); background: var(--td-bg-color-container); }
.trajectory__overview span, .trajectory__overview small, .trajectory__table small, .trajectory__inspector header small { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.trajectory__overview strong { font-size: var(--app-text-base); font-variant-numeric: tabular-nums; }
.trajectory__split { display: grid; flex: 1; min-height: 0; grid-template-columns: minmax(320px, 1.2fr) minmax(320px, 1fr); overflow: hidden; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-md); background: var(--td-bg-color-container); }
.trajectory__table-scroll { min-width: 0; overflow: auto; border-right: 1px solid var(--td-component-stroke); }
.trajectory__table { width: 100%; border-collapse: collapse; text-align: left; font-size: var(--app-text-sm); }
.trajectory__table th { position: sticky; top: 0; z-index: 1; padding: 9px 10px; background: var(--td-bg-color-secondarycontainer); color: var(--td-text-color-secondary); font-weight: 500; }
.trajectory__table td { max-width: 340px; padding: 10px; border-top: 1px solid var(--td-component-stroke); vertical-align: top; }
.trajectory__table tbody tr { cursor: pointer; }
.trajectory__table tbody tr:hover { background: var(--td-bg-color-container-hover); }
.trajectory__table tbody tr[aria-selected="true"] { background: var(--td-brand-color-light); }
.trajectory__table tbody tr:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: -2px; }
.trajectory__table td:first-child strong, .trajectory__table td:first-child small, .trajectory__table td:last-child span, .trajectory__table td:last-child small { display: block; }
.trajectory__table td:first-child small, .trajectory__table td:last-child small { margin-top: 4px; }
.trajectory__summary { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trajectory__inspector { min-width: 0; overflow: auto; padding: 14px; }
.trajectory__inspector header h2 { margin: 0 0 3px; font-size: var(--app-text-md); }
.trajectory__metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 12px 0; }
.trajectory__metrics div { display: grid; gap: 3px; min-width: 0; padding: 8px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); }
.trajectory__metrics span { color: var(--td-text-color-secondary); font-size: var(--app-text-xs); }
.trajectory__metrics strong { overflow-wrap: anywhere; font-size: var(--app-text-sm); font-variant-numeric: tabular-nums; }
.trajectory__inspector details { margin-top: 10px; border-top: 1px solid var(--td-component-stroke); }
.trajectory__inspector summary { padding: 9px 0; cursor: pointer; font-weight: 600; }
.trajectory__message { margin: 7px 0; padding: 8px; border-radius: var(--app-radius-sm); background: var(--td-bg-color-secondarycontainer); }
.trajectory__message strong { text-transform: capitalize; }
.trajectory pre { overflow: auto; max-height: 36vh; margin: 6px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.55 var(--app-font-mono); }
.trajectory__error { color: var(--td-error-color); }
@media (max-width: 900px) { .trajectory { overflow: auto; } .trajectory__split { min-height: 560px; grid-template-columns: minmax(260px, 1fr); grid-template-rows: minmax(240px, 0.8fr) minmax(280px, 1fr); } .trajectory__table-scroll { border-right: 0; border-bottom: 1px solid var(--td-component-stroke); } }
</style>
