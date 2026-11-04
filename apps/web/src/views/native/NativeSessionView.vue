<template>
  <div class="native-session">
    <header class="native-session__header">
      <router-link class="native-session__back" to="/platform/native">← {{ $t('nativeRuns.back') }}</router-link>
      <div class="native-session__status">
        <t-tag v-if="run" :theme="statusTheme" variant="light" data-testid="native-run-status">
          {{ statusLabel }}
        </t-tag>
        <t-button v-if="canCancel(run)" size="small" theme="danger" variant="outline" :disabled="busy"
          data-testid="native-cancel" @click="cancelRun">
          {{ $t('nativeRuns.cancel') }}
        </t-button>
      </div>
    </header>

    <t-loading :loading="loading" size="small">
      <NativeWatchdogBanner v-if="showWatchdogBanner(run)" class="native-session__banner"
        :can-hint="canSteer(run)" :busy="busy" @acknowledge="acknowledge" @cancel="cancelRun" @hint="sendHint" />

      <t-alert v-if="errorText" theme="error" :message="errorText" class="native-session__alert" />
      <t-alert v-if="streamError" theme="warning" :message="$t('nativeRuns.streamError', { message: streamError })"
        class="native-session__alert" />

      <section class="native-session__transcript" aria-live="polite" data-testid="native-transcript">
        <article v-for="message in messages" :key="message.id" class="native-session__message"
          :class="`is-${message.role}`">
          <div class="native-session__role">{{ roleLabel(message.role) }}</div>
          <div class="native-session__content">{{ message.content }}</div>
        </article>

        <article v-if="liveSegments.length > 0" class="native-session__message is-assistant is-live">
          <div class="native-session__role">{{ $t('nativeRuns.assistant') }}</div>
          <div v-for="segment in liveSegments" :key="segment.turn" class="native-session__content">
            {{ segment.text }}
          </div>
        </article>

        <ul v-if="calls.length > 0" class="native-session__tools" data-testid="native-tool-calls">
          <li v-for="call in calls" :key="call.invocationId" :class="`is-${call.status}`">
            {{ toolLabel(call) }}
            <span v-if="call.errorCode" class="native-session__error-code">({{ call.errorCode }})</span>
          </li>
        </ul>

        <p v-if="failureText" class="native-session__failure" role="status" data-testid="native-failure">
          {{ failureText }}
        </p>
        <p v-if="run?.status === 'queued' && run.queue_position" class="native-session__queued" data-testid="native-queued">
          {{ $t('nativeRuns.queued', { count: run.queue_position - 1 }) }}
        </p>
      </section>

      <section v-if="needsInput(run) && pendingInput" class="native-session__input-request" data-testid="native-input-request">
        <h3 class="native-session__input-title">{{ $t('nativeRuns.input.title') }}</h3>
        <p class="native-session__input-question">{{ pendingInput.question }}</p>
        <div v-if="pendingInput.candidates.length > 0" class="native-session__candidates">
          <t-button v-for="candidate in pendingInput.candidates" :key="candidate" variant="outline" size="small"
            :disabled="busy" @click="answer(candidate)">
            {{ candidate }}
          </t-button>
        </div>
        <form class="native-session__input-form" @submit.prevent="answer(answerText.trim())">
          <t-input v-model="answerText" :placeholder="$t('nativeRuns.input.placeholder')" :maxlength="100000"
            :disabled="busy" />
          <t-button type="submit" theme="primary" :disabled="busy || !answerText.trim()">
            {{ $t('nativeRuns.input.submit') }}
          </t-button>
        </form>
      </section>

      <form class="native-session__composer" @submit.prevent="send">
        <t-textarea v-model="draft" :autosize="{ minRows: 2, maxRows: 8 }" :maxlength="100000"
          :placeholder="$t('nativeRuns.composerPlaceholder')" :disabled="submitting" data-testid="native-composer"
          @keydown="onComposerKeydown" />
        <t-button type="submit" theme="primary" :disabled="submitting || !draft.trim()" :loading="submitting"
          data-testid="native-send">
          {{ $t('nativeRuns.send') }}
        </t-button>
      </form>
    </t-loading>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import { getConversation, type ConversationMessage } from '@/api/native-runs'
import { useNativeRun } from '@/composables/useNativeRun'
import NativeWatchdogBanner from './NativeWatchdogBanner.vue'
import {
  assistantSegments,
  canCancel,
  canSteer,
  failureCode,
  isTerminal,
  needsInput,
  showWatchdogBanner,
  toolCalls,
  type ToolCallItem,
} from './nativeRunState'

const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

const sessionId = computed(() => String(route.params.sessionId ?? ''))
const tenantId = computed(() => authStore.effectiveTenantId)
const native = useNativeRun(() => tenantId.value)

const messages = ref<ConversationMessage[]>([])
const loading = ref(false)
const submitting = ref(false)
const busy = ref(false)
const draft = ref('')
const answerText = ref('')
const errorText = ref('')

const run = computed(() => native.state.value.run)
const streamError = computed(() => native.streamError.value)
const pendingInput = computed(() => native.pendingInput.value)
const calls = computed<ToolCallItem[]>(() => toolCalls(native.state.value.events))
const liveSegments = computed(() => (run.value && !isTerminal(run.value) ? assistantSegments(native.state.value.events) : []))

const STATUS_THEME: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'danger'> = {
  queued: 'default',
  running: 'primary',
  waiting_input: 'warning',
  waiting_approval: 'warning',
  completed: 'success',
  failed: 'danger',
  cancelled: 'default',
  interrupted: 'danger',
}

const statusTheme = computed(() => (run.value ? STATUS_THEME[run.value.status] ?? 'default' : 'default'))
const statusLabel = computed(() => (run.value ? t(`nativeRuns.status.${run.value.status}`) : ''))
const failureText = computed(() => {
  const code = failureCode(run.value)
  if (code) return t('nativeRuns.failure', { code })
  if (run.value?.status === 'cancelled') return t('nativeRuns.cancelled')
  return ''
})

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const data = error as { message?: unknown; error?: unknown } | null
  if (data && typeof data.message === 'string') return data.message
  if (data && typeof data.error === 'string') return data.error
  return fallback
}

function roleLabel(role: string): string {
  if (role === 'user') return t('nativeRuns.user')
  if (role === 'assistant') return t('nativeRuns.assistant')
  return t('nativeRuns.system')
}

function toolLabel(call: ToolCallItem): string {
  if (call.status === 'completed') return t('nativeRuns.toolCompleted', { name: call.name })
  if (call.status === 'failed') return t('nativeRuns.toolFailed', { name: call.name })
  return t('nativeRuns.toolRunning', { name: call.name })
}

/** Reload persisted messages; used on open and after a Run ends so the transcript matches the server. */
async function reloadMessages() {
  if (!tenantId.value || !sessionId.value) return
  const page = await getConversation(tenantId.value, sessionId.value)
  messages.value = page.messages
}

async function open() {
  errorText.value = ''
  if (!tenantId.value) {
    errorText.value = t('nativeRuns.noSpace')
    return
  }
  loading.value = true
  try {
    messages.value = await native.loadSession(sessionId.value)
  } catch (error) {
    errorText.value = messageOf(error, t('nativeRuns.loadError'))
  } finally {
    loading.value = false
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || !tenantId.value) return
  submitting.value = true
  errorText.value = ''
  try {
    await native.send(sessionId.value, text)
    draft.value = ''
  } catch (error) {
    MessagePlugin.error(messageOf(error, t('nativeRuns.sendError')))
  } finally {
    submitting.value = false
  }
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    void send()
  }
}

/** Run an action on the current Run. Errors surface as a message and never change the local Run view. */
async function act(action: () => Promise<void>, fallback: string) {
  busy.value = true
  try {
    await action()
  } catch (error) {
    MessagePlugin.error(messageOf(error, fallback))
  } finally {
    busy.value = false
  }
}

const acknowledge = () => act(() => native.acknowledge(), t('nativeRuns.loadError'))
const cancelRun = () => act(() => native.cancel(), t('nativeRuns.loadError'))
const sendHint = (content: string) => act(async () => {
  await native.steer(content)
  MessagePlugin.success(t('nativeRuns.hintSent'))
}, t('nativeRuns.sendError'))
const answer = (response: string) => act(async () => {
  await native.answerInput(response)
  answerText.value = ''
}, t('nativeRuns.sendError'))

// When a Run reaches a terminal state, the persisted transcript now holds its answer. Reload it so the
// live text and the stored message do not both show.
watch(() => run.value?.status, (status, previous) => {
  if (status && previous && status !== previous && isTerminal(run.value)) {
    reloadMessages().catch(() => { /* keep the transcript we have */ })
  }
})

watch(() => route.params.sessionId, () => {
  native.dispose()
  void open()
})

watch(tenantId, () => void open())

onMounted(open)
onBeforeUnmount(() => native.dispose())
</script>

<style lang="less" scoped>
.native-session {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  max-width: 880px;
  margin: 0 auto;
  width: 100%;
  min-height: 100%;
  box-sizing: border-box;
}

.native-session__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.native-session__back {
  color: var(--td-brand-color);
  text-decoration: none;
}

.native-session__status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.native-session__transcript {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.native-session__message {
  padding: 12px 16px;
  border-radius: var(--app-radius-md);
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke);

  &.is-user {
    background: var(--td-brand-color-light);
  }

  &.is-system {
    color: var(--td-text-color-secondary);
  }
}

.native-session__role {
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);
  margin-bottom: 4px;
}

.native-session__content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.native-session__tools {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--app-text-sm);
  color: var(--td-text-color-secondary);

  .is-failed {
    color: var(--td-error-color);
  }
}

.native-session__error-code {
  font-family: var(--td-font-family-code);
}

.native-session__failure {
  margin: 0;
  color: var(--td-error-color);
}

.native-session__queued {
  margin: 0;
  color: var(--td-text-color-secondary);
}

.native-session__input-request {
  padding: 16px;
  border-radius: var(--app-radius-md);
  border: 1px solid var(--td-warning-color-4);
  background: var(--td-warning-color-1);
}

.native-session__input-title {
  margin: 0 0 8px;
  font-size: var(--app-text-lg);
}

.native-session__input-question {
  margin: 0 0 12px;
  white-space: pre-wrap;
}

.native-session__candidates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.native-session__input-form {
  display: flex;
  gap: 8px;

  :deep(.t-input) {
    flex: 1;
  }
}

.native-session__composer {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  position: sticky;
  bottom: 0;
  padding-top: 8px;
  background: var(--td-bg-color-page);

  :deep(.t-textarea) {
    flex: 1;
  }
}

@media (max-width: 480px) {
  .native-session {
    padding: 16px;
  }

  .native-session__composer {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
