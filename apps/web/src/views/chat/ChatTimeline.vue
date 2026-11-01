<script setup lang="ts">
/**
 * Run timeline: the agent's text and its steps (tools, approvals, questions, deep thinking) in the order
 * they happened, with a totals line above (thinking turns, tool calls, seconds). Each step shows an icon
 * and a text state, so meaning never depends on colour alone.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RunStats, TimelineItem, ToolState } from '../../composables/useConversation'

const props = defineProps<{ items: TimelineItem[]; stats: RunStats; showStats: boolean }>()
const { t } = useI18n()

const toolLabels: Record<ToolState, string> = {
  running: 'chat.toolRunning', completed: 'chat.toolCompleted', failed: 'chat.toolFailed',
  unknown: 'chat.toolUnknown', cancelled: 'chat.toolCancelled', denied: 'chat.toolDenied',
}
const toolGlyphs: Record<ToolState, string> = { running: '◌', completed: '✓', failed: '✕', unknown: '?', cancelled: '–', denied: '⊘' }

const summary = computed(() => t('chat.stepsSummary', { turns: props.stats.turns, tools: props.stats.tools, seconds: props.stats.seconds }))
</script>

<template>
  <div class="timeline">
    <p v-if="showStats && items.length" class="timeline-summary">{{ summary }}</p>
    <template v-for="item in items" :key="item.id">
      <div v-if="item.kind === 'message' && item.role === 'user'" class="row row--user">
        <p class="visually-hidden">{{ t('chat.you') }}</p>
        <div class="bubble">{{ item.content }}</div>
      </div>

      <div v-else-if="item.kind === 'message'" class="row row--agent">
        <p class="visually-hidden">{{ t('chat.agent') }}</p>
        <div class="message-text">{{ item.content }}</div>
      </div>

      <details v-else-if="item.kind === 'thinking'" class="step step--thinking">
        <summary>{{ t('chat.thinking') }}</summary>
        <p class="message-text">{{ item.content }}</p>
      </details>

      <div v-else-if="item.kind === 'tool'" class="step" :class="`step--${item.state}`">
        <div class="step-head">
          <span class="glyph" aria-hidden="true">{{ toolGlyphs[item.state] }}</span>
          <span class="step-name">{{ item.name }}</span>
          <span class="step-state">{{ t(toolLabels[item.state]) }}</span>
        </div>
        <details v-if="item.summary || item.progress.length" class="step-detail">
          <summary>{{ t('chat.toolResult') }}</summary>
          <pre>{{ [...item.progress, item.summary].filter(Boolean).join('\n') }}</pre>
        </details>
      </div>

      <div v-else-if="item.kind === 'approval'" class="step" :class="`step--approval-${item.state}`">
        <div class="step-head">
          <span class="glyph" aria-hidden="true">{{ item.state === 'pending' ? '!' : item.state === 'approved' ? '✓' : '✕' }}</span>
          <span class="step-name">{{ item.state === 'pending' ? t('chat.approvalRequested', { name: item.name }) : item.name }}</span>
          <span class="step-state">{{ item.state === 'pending' ? '' : item.state === 'approved' ? t('chat.approvalApproved') : t('chat.approvalRejected') }}</span>
        </div>
      </div>

      <div v-else-if="item.kind === 'input'" class="step">
        <div class="step-head">
          <span class="glyph" aria-hidden="true">?</span>
          <span class="step-name">{{ t('chat.inputRequested') }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.timeline { display: grid; gap: 14px; }
.timeline-summary { margin: 0; font-size: 13px; color: var(--muted-text); }
.row { display: flex; }
.row--user { justify-content: flex-end; }
.bubble { max-width: 78%; padding: 10px 14px; border-radius: 12px; background: var(--selected); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
.message-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; margin: 0; }
.step { display: grid; gap: 6px; padding: 8px 12px; border-left: 2px solid var(--border); font-size: 14px; }
.step-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.glyph { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; border: 1px solid var(--border); font-size: 12px; flex: none; }
.step-name { overflow-wrap: anywhere; }
.step-state { color: var(--muted-text); font-size: 13px; }
.step--failed .glyph, .step--approval-rejected .glyph { color: var(--el-color-danger); border-color: var(--el-color-danger); }
.step--completed .glyph, .step--approval-approved .glyph { color: var(--el-color-success); border-color: var(--el-color-success); }
.step--approval-pending { border-left-color: var(--el-color-warning); }
.step-detail summary, .step--thinking summary { cursor: pointer; color: var(--muted-text); font-size: 13px; }
.step-detail pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; font-size: 13px; line-height: 1.6; margin: 6px 0 0; }
.step--thinking .message-text { color: var(--muted-text); font-size: 13px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; margin: 0; }
</style>
