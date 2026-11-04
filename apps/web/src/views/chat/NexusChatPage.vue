<template>
  <!--
    对话页（主聊天路由：/platform/creatChat 与 /platform/chat/:chatid）。
    布局参照 WeKnora 对话页：居中的欢迎区 / 居中的消息流，底部圆角输入框，
    用户消息为右侧气泡，助手消息为左侧 Markdown 正文，工具调用以过程条展示。
    数据全部来自平台 Native API（会话、Run、事件），见 openspec/changes/2026-11-04-weknora-chat-dialog。
  -->
  <div class="nexus-chat" :class="{ 'is-welcome': isWelcome }">
    <header v-if="!isWelcome" class="nexus-chat__header">
      <t-tag v-if="run" :theme="statusTheme" variant="light" data-testid="chat-run-status">{{ statusLabel }}</t-tag>
    </header>

    <div class="nexus-chat__scroll" ref="scrollRef">
      <div class="nexus-chat__column">
        <t-loading :loading="loading" size="small">
          <NativeWatchdogBanner v-if="showWatchdogBanner(run)" class="nexus-chat__banner"
            :can-hint="canSteer(run)" :busy="busy" @acknowledge="acknowledge" @cancel="cancelRun" @hint="sendHint" />

          <t-alert v-if="errorText" theme="error" :message="errorText" class="nexus-chat__alert" />
          <t-alert v-if="streamError" theme="warning" :message="$t('nativeRuns.streamError', { message: streamError })"
            class="nexus-chat__alert" />

          <section v-if="!isWelcome" class="nexus-chat__transcript" aria-live="polite" data-testid="chat-transcript">
            <template v-for="message in messages" :key="message.id">
              <div v-if="message.role === 'user'" class="nexus-chat__turn is-user">
                <div class="nexus-chat__bubble">{{ message.content }}</div>
              </div>
              <div v-else class="nexus-chat__turn is-assistant">
                <div class="nexus-chat__markdown" v-html="renderMarkdown(message.content, false)" />
              </div>
            </template>

            <!-- 本页提交、尚未写入持久化消息的用户输入：在 Run 结束并重新加载消息前先显示。 -->
            <div v-for="(text, index) in pendingUsers" :key="`pending-${index}`" class="nexus-chat__turn is-user">
              <div class="nexus-chat__bubble">{{ text }}</div>
            </div>

            <!-- 当前运行：WeKnora 的智能体时间线组件，输入由 toAgentEventStream 从 Run 事件映射而来。 -->
            <div v-if="liveSession" class="nexus-chat__turn is-assistant is-live" data-testid="chat-live-stream">
              <AgentStreamDisplay class="nexus-chat__stream" :session="liveSession" />
            </div>

            <p v-if="failureText" class="nexus-chat__status-line is-failure" role="status" data-testid="chat-failure">
              {{ failureText }}
            </p>
            <p v-if="run?.status === 'queued' && run.queue_position" class="nexus-chat__status-line" data-testid="chat-queued">
              {{ $t('nativeRuns.queued', { count: run.queue_position - 1 }) }}
            </p>
          </section>

          <section v-if="needsInput(run) && pendingInput" class="nexus-chat__input-request" data-testid="chat-input-request">
            <h3 class="nexus-chat__input-title">{{ $t('nativeRuns.input.title') }}</h3>
            <p class="nexus-chat__input-question">{{ pendingInput.question }}</p>
            <div v-if="pendingInput.candidates.length > 0" class="nexus-chat__candidates">
              <t-button v-for="candidate in pendingInput.candidates" :key="candidate" variant="outline" size="small"
                :disabled="busy" @click="answer(candidate)">
                {{ candidate }}
              </t-button>
            </div>
            <form class="nexus-chat__input-form" @submit.prevent="answer(answerText.trim())">
              <t-input v-model="answerText" :placeholder="$t('nativeRuns.input.placeholder')" :maxlength="100000"
                :disabled="busy" />
              <t-button type="submit" theme="primary" :disabled="busy || !answerText.trim()">
                {{ $t('nativeRuns.input.submit') }}
              </t-button>
            </form>
          </section>
        </t-loading>
      </div>
    </div>

    <div class="nexus-chat__composer-wrap">
      <h1 v-if="isWelcome" class="nexus-chat__welcome">{{ $t('nexusChat.welcome') }}</h1>
      <!-- 输入区复用 WeKnora 的 Input-field，nexus-mode 下只保留文本、发送、追加指令与停止。 -->
      <InputField nexus-mode class="nexus-chat__input" data-testid="chat-composer" :auto-focus="isWelcome"
        :is-replying="isReplying" :can-steer="canSteer(run)"
        @send-msg="onSendMsg" @steer-msg="onSteerMsg" @stop-generation="cancelRun">
        <template #controls>
          <t-select v-if="isWelcome" v-model="selectedAgent" size="small" class="nexus-chat__agent"
            :placeholder="$t('nativeRuns.agentPlaceholder')" :loading="loadingAgents" :options="agentOptions"
            :disabled="agentOptions.length === 0" data-testid="chat-agent-select" />
        </template>
      </InputField>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import {
  createSession as createSessionApi,
  getConversation,
  listAgents,
  type AgentView,
  type ConversationMessage,
} from '@/api/native-runs'
import { useNativeRun } from '@/composables/useNativeRun'
import NativeWatchdogBanner from '@/views/native/NativeWatchdogBanner.vue'
import {
  canCancel,
  canSteer,
  failureCode,
  isActive,
  isTerminal,
  needsInput,
  showWatchdogBanner,
} from '@/views/native/nativeRunState'
import { configureMarkedForChatMarkdown, createChatMarkdownRenderer, renderChatMarkdown } from '@/utils/chatMarkdownRenderer'
import AgentStreamDisplay from '@/views/chat/components/AgentStreamDisplay.vue'
import InputField from '@/components/Input-field.vue'
import { toAgentEventStream } from '@/utils/nexusAgentEvents'
import { safeMarkdownToHTML, sanitizeMarkdownHTML } from '@/utils/security'
import { deriveSessionTitle } from '@/utils/nexusChatTitle'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const sessionId = computed(() => String(route.params.chatid ?? ''))
const isWelcome = computed(() => !sessionId.value)
const tenantId = computed(() => authStore.effectiveTenantId)
const native = useNativeRun(() => tenantId.value)

const messages = ref<ConversationMessage[]>([])
const loading = ref(false)
const loadingAgents = ref(false)
const busy = ref(false)
const answerText = ref('')
const errorText = ref('')
const agents = ref<AgentView[]>([])
const selectedAgent = ref<string | undefined>(undefined)
const scrollRef = ref<HTMLElement>()
const pendingUsers = ref<string[]>([])
/** 欢迎页创建的会话 ID。路由切换到它时不再重新加载，避免覆盖刚开始的 Run 状态。 */
let createdSessionId = ''

const run = computed(() => native.state.value.run)
const streamError = computed(() => native.streamError.value)
const pendingInput = computed(() => native.pendingInput.value)
/**
 * 当前运行的时间线数据。运行结束后，只要还有待显示的用户输入（即持久化消息尚未重新加载），
 * 时间线继续保留，直到消息重新加载，避免同一回答同时以流式和持久化两种形式出现。
 */
const liveSession = computed(() => {
  const current = run.value
  if (!current) return null
  if (isTerminal(current) && pendingUsers.value.length === 0) return null
  const events = native.state.value.events
  if (events.length === 0 && !isActive(current)) return null
  return {
    id: current.id,
    assistant_message_id: current.id,
    request_id: current.id,
    isAgentMode: true,
    agentEventStream: toAgentEventStream(events, current.status),
    knowledge_references: [],
  }
})

const agentOptions = computed(() => agents.value.map(agent => ({
  label: agent.name,
  value: agent.published_version_id as string,
})))

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
const isReplying = computed(() => isActive(run.value))
const statusTheme = computed(() => (run.value ? STATUS_THEME[run.value.status] ?? 'default' : 'default'))
const statusLabel = computed(() => (run.value ? t(`nativeRuns.status.${run.value.status}`) : ''))
const failureText = computed(() => {
  const code = failureCode(run.value)
  if (code) return t('nativeRuns.failure', { code })
  if (run.value?.status === 'cancelled') return t('nativeRuns.cancelled')
  return ''
})

// 与 botmsg.vue 相同的 Markdown 管线：marked + KaTeX，输出经 DOMPurify 净化。
configureMarkedForChatMarkdown()
const markdownRenderer = createChatMarkdownRenderer()
function renderMarkdown(text: string, streaming: boolean): string {
  return renderChatMarkdown(text, {
    renderer: markdownRenderer,
    escapeMarkdown: safeMarkdownToHTML,
    sanitizeHtml: sanitizeMarkdownHTML,
    streaming,
  })
}

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const data = error as { message?: unknown; error?: unknown } | null
  if (data && typeof data.message === 'string') return data.message
  if (data && typeof data.error === 'string') return data.error
  return fallback
}



async function loadAgents() {
  const tenant = tenantId.value
  if (!tenant) return
  loadingAgents.value = true
  try {
    // 只有已发布版本可以创建会话；草稿没有可运行的版本。
    agents.value = (await listAgents(tenant)).filter(agent => agent.published_version_id !== null)
    if (!selectedAgent.value || !agents.value.some(agent => agent.published_version_id === selectedAgent.value)) {
      selectedAgent.value = agents.value[0]?.published_version_id ?? undefined
    }
  } catch (error) {
    errorText.value = messageOf(error, t('nativeRuns.loadError'))
  } finally {
    loadingAgents.value = false
  }
}

async function openSession() {
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

/** 运行结束后重新读取持久化的消息，使流式文本与已保存的回答不会同时出现。 */
async function reloadMessages() {
  if (!tenantId.value || !sessionId.value) return
  const page = await getConversation(tenantId.value, sessionId.value)
  messages.value = page.messages
}

/** 发送一条消息：欢迎页先创建会话，会话页直接提交新的 Run（服务端排队，忙时不阻止）。 */
async function sendText(text: string) {
  if (!tenantId.value) return
  errorText.value = ''
  try {
    if (isWelcome.value) {
      if (!selectedAgent.value) {
        MessagePlugin.warning(t('nexusChat.needAgent'))
        return
      }
      const session = await createSessionApi(tenantId.value, selectedAgent.value, deriveSessionTitle(text))
      createdSessionId = session.id
      pendingUsers.value = [text]
      await native.send(session.id, text)
      await router.replace(`/platform/chat/${session.id}`)
    } else {
      pendingUsers.value = [...pendingUsers.value, text]
      await native.send(sessionId.value, text)
    }
  } catch (error) {
    MessagePlugin.error(messageOf(error, t('nativeRuns.sendError')))
  }
}

const onSendMsg = (text: string) => { void sendText(text) }

/** 运行中发送的追加指令：作为 steer 注入当前 Run，并显示为待显示的用户消息。 */
const onSteerMsg = (text: string) => {
  pendingUsers.value = [...pendingUsers.value, text]
  void sendHint(text)
}

/** 对当前 Run 执行操作；失败只提示，不改变本地 Run 视图。 */
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

watch(() => run.value?.status, (status, previous) => {
  if (status && previous && status !== previous && isTerminal(run.value)) {
    reloadMessages()
      .then(() => { pendingUsers.value = [] })
      .catch(() => { /* 保留当前消息与待显示的用户输入 */ })
  }
})

// 新消息或流式文本增长时保持滚动到底部。
watch(
  () => [messages.value.length, pendingUsers.value.length, native.state.value.events.length],
  async () => {
    await nextTick()
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

watch(() => route.params.chatid, (id) => {
  // 欢迎页刚创建的会话：Run 已在进行中，保留其流式状态，不做 dispose 与重新加载。
  if (id && String(id) === createdSessionId) return
  native.dispose()
  pendingUsers.value = []
  if (!id) {
    messages.value = []
    errorText.value = ''
    void loadAgents()
    return
  }
  void openSession()
})

watch(tenantId, () => {
  if (isWelcome.value) void loadAgents()
  else void openSession()
})

onMounted(() => {
  if (isWelcome.value) void loadAgents()
  else void openSession()
})
onBeforeUnmount(() => native.dispose())
</script>

<style lang="less" scoped>
.nexus-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  width: 100%;
  box-sizing: border-box;
  background: var(--td-bg-color-container);
}

.nexus-chat__header {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  padding: 12px 24px 0;
}

.nexus-chat__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 16px 8px;
}

.nexus-chat.is-welcome .nexus-chat__scroll {
  flex: 0;
  padding: 0;
}

.nexus-chat__column {
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.nexus-chat__transcript {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.nexus-chat__turn {
  display: flex;

  &.is-user {
    justify-content: flex-end;
  }

  &.is-assistant {
    justify-content: flex-start;
  }
}

.nexus-chat__bubble {
  max-width: 80%;
  padding: 10px 16px;
  border-radius: 16px 16px 4px 16px;
  background: var(--td-brand-color-light);
  color: var(--td-text-color-primary);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}

.nexus-chat__markdown {
  width: 100%;
  color: var(--td-text-color-primary);
  line-height: 1.75;
  word-break: break-word;

  :deep(p) {
    margin: 0 0 8px;
  }

  :deep(pre) {
    overflow-x: auto;
    padding: 12px;
    border-radius: var(--app-radius-sm);
    background: var(--td-bg-color-secondarycontainer);
  }

  :deep(table) {
    display: block;
    overflow-x: auto;
    border-collapse: collapse;
  }

  :deep(th),
  :deep(td) {
    padding: 6px 10px;
    border: 1px solid var(--td-component-stroke);
  }
}



.nexus-chat__status-line {
  margin: 0;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-sm);

  &.is-failure {
    color: var(--td-error-color);
  }
}

.nexus-chat__input-request {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);
}

.nexus-chat__input-title {
  margin: 0;
  font-size: var(--app-text-base);
  font-weight: 600;
}

.nexus-chat__input-question {
  margin: 0;
}

.nexus-chat__candidates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.nexus-chat__input-form {
  display: flex;
  gap: 8px;
}

.nexus-chat__composer-wrap {
  flex-shrink: 0;
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  padding: 12px 16px 20px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: stretch;
}

.nexus-chat.is-welcome {
  justify-content: center;

  .nexus-chat__composer-wrap {
    padding-bottom: 0;
  }
}

.nexus-chat__welcome {
  margin: 0 0 8px;
  text-align: center;
  font-size: var(--app-text-3xl);
  font-weight: 600;
  color: var(--td-text-color-primary);
}

/* 子组件根节点需要占满列宽：Input-field 与流式展示都以 scoped 根类接入。 */
.nexus-chat__input,
.nexus-chat__stream {
  width: 100%;
  min-width: 0;
}

.nexus-chat__agent {
  width: 220px;
}


@media (max-width: 720px) {
  .nexus-chat__scroll {
    padding: 16px 12px 8px;
  }

  .nexus-chat__agent {
    width: 160px;
  }
}
</style>
