<template>
  <!-- Nexus only: a memory draft the model proposed in this Run (openspec 2026-11-06-memory-evolution E1).
       The owner publishes or discards it here instead of in the memory settings page. -->
  <div v-if="actions" class="action-card memory-draft-card" :class="{ 'action-pending': state === 'pending' }">
    <div class="action-header no-results">
      <div class="action-title">
        <ChatTimelineIcon class="action-title-icon" name="bookmark" :active="state === 'pending'" />
        <span class="action-name">{{ $t('agentStream.memoryDraft.title') }}</span>
        <span class="memory-draft-kind">{{ kindLabel }}</span>
        <span class="memory-draft-status" role="status">{{ statusText }}</span>
      </div>
    </div>

    <div class="memory-draft-target">
      {{ baseEntry ? $t('agentStream.memoryDraft.editsEntry', { title: baseEntry.title }) : $t('agentStream.memoryDraft.newEntry') }}
    </div>
    <div class="memory-draft-body">{{ diff }}</div>
    <div v-if="conflicts.length" class="memory-draft-hint">
      {{ $t('agentStream.memoryDraft.conflictHint', { titles: conflicts.join('、') }) }}
    </div>
    <div v-if="similar.length" class="memory-draft-hint">
      {{ $t('agentStream.memoryDraft.similarHint', { titles: similar.join('、') }) }}
    </div>

    <div v-if="state === 'pending'" class="memory-draft-actions">
      <label class="memory-draft-label" :for="`memory-draft-${draftId}`">{{ $t('agentStream.memoryDraft.titleLabel') }}</label>
      <t-input :id="`memory-draft-${draftId}`" v-model="title" size="small" :maxlength="160" :disabled="submitting"
        :placeholder="$t('agentStream.memoryDraft.titlePlaceholder')" />
      <div class="memory-draft-buttons">
        <t-button size="small" variant="outline" :disabled="submitting" @click="submit(false)">
          {{ $t('agentStream.memoryDraft.reject') }}
        </t-button>
        <t-button size="small" theme="primary" :loading="submitting" :disabled="submitting" @click="submit(true)">
          {{ $t('agentStream.memoryDraft.publish') }}
        </t-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import ChatTimelineIcon from '@/components/ChatTimelineIcon.vue'
import { useNexusChatActions } from '@/composables/nexusChatActions'

type CardState = 'checking' | 'pending' | 'published' | 'rejected' | 'handled'

const props = defineProps<{
  draftId: string
  kind: string
  diff: string
  topic: string
  baseEntry: { id: string; title: string; version: number } | null
  conflicts: string[]
  similar: string[]
}>()

const { t } = useI18n()
const actions = useNexusChatActions()
const state = ref<CardState>('checking')
const submitting = ref(false)
// An edit keeps its entry's title unless the owner changes it; a new entry starts from its topic.
const title = ref(props.baseEntry?.title || props.topic || props.diff.slice(0, 20))

const kindLabel = computed(() => (['memory', 'sop', 'profile'].includes(props.kind)
  ? t(`agentStream.memoryDraft.kinds.${props.kind}`) : t('agentStream.memoryDraft.kinds.memory')))

const statusText = computed(() => {
  switch (state.value) {
    case 'checking': return t('agentStream.memoryDraft.checking')
    case 'published': return t('agentStream.memoryDraft.published')
    case 'rejected': return t('agentStream.memoryDraft.rejected')
    case 'handled': return t('agentStream.memoryDraft.handled')
    default: return ''
  }
})

onMounted(async () => {
  if (!actions) return
  // History replays the card: ask the server whether the draft still awaits review.
  const pending = await actions.isMemoryDraftPending(props.draftId)
  state.value = pending === false ? 'handled' : 'pending'
})

async function submit(approve: boolean) {
  if (!actions || submitting.value) return
  if (approve && !title.value.trim()) {
    MessagePlugin.warning(t('agentStream.memoryDraft.titleRequired'))
    return
  }
  submitting.value = true
  try {
    state.value = await actions.reviewMemoryDraft(props.draftId, approve, title.value.trim())
  } catch (error) {
    const message = error instanceof Error ? error.message : ''
    MessagePlugin.error(message || t('agentStream.memoryDraft.failed'))
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped lang="less">
.memory-draft-card {
  padding-bottom: 8px;
}

.memory-draft-kind,
.memory-draft-status {
  margin-left: 8px;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
}

.memory-draft-target,
.memory-draft-hint {
  margin: 4px 12px 0;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
}

.memory-draft-hint {
  color: var(--td-warning-color);
}

.memory-draft-body {
  margin: 6px 12px 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: var(--app-text-md);
  color: var(--td-text-color-primary);
}

.memory-draft-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 8px 12px 0;
}

.memory-draft-label {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
}

.memory-draft-actions :deep(.t-input__wrap) {
  flex: 1 1 180px;
  min-width: 0;
}

.memory-draft-buttons {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
</style>
