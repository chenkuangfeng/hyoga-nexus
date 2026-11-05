<template>
  <!--
    对话页（主聊天路由：/platform/creatChat 与 /platform/chat/:chatid）。
    布局参照 WeKnora 对话页：居中的欢迎区 / 居中的消息流，底部圆角输入框，
    用户消息为右侧气泡，助手消息为左侧 Markdown 正文，工具调用以过程条展示。
    数据全部来自平台 Native API（会话、Run、事件），见 openspec/changes/2026-11-04-weknora-chat-dialog。
  -->
  <div class="nexus-chat" :class="{ 'is-welcome': isWelcome, 'is-compact': compact }">
    <header v-if="!isWelcome" class="nexus-chat__header">
      <!-- 与 WeKnora ChatHeader 的标题样式一致；平台暂无改名、置顶与删除接口，不提供菜单。 -->
      <div class="chat-header">
        <h1 class="chat-header__title" :title="sessionTitle">
          <span class="chat-header__title-text" data-testid="chat-title">{{ sessionTitle }}</span>
        </h1>
      </div>
      <t-tag v-if="run" :theme="statusTheme" variant="light" class="nexus-chat__status" data-testid="chat-run-status">{{ statusLabel }}</t-tag>
    </header>

    <div class="nexus-chat__scroll" ref="scrollRef" @scroll="handleScroll">
      <div class="nexus-chat__column">
        <!-- 欢迎态：与 WeKnora creatChat 一致，标题与输入框一起垂直居中。 -->
        <div v-if="isWelcome && !compact" class="dialogue-title" data-testid="chat-welcome-title">
          <span>{{ $t('createChat.title') }}</span>
        </div>

        <!-- 与 WeKnora 对话页一致：首次加载历史时显示消息骨架屏。 -->
        <div v-if="loading && messages.length === 0" class="msg-skeleton-list" data-testid="chat-skeleton">
          <div class="msg-skeleton msg-skeleton-user">
            <t-skeleton animation="gradient" :row-col="[{ width: '45%', height: '36px', type: 'rect' }]" />
          </div>
          <div class="msg-skeleton msg-skeleton-bot">
            <t-skeleton animation="gradient"
              :row-col="[{ width: '80%', height: '16px' }, { width: '100%', height: '16px' }, { width: '60%', height: '16px' }]" />
          </div>
          <div class="msg-skeleton msg-skeleton-user">
            <t-skeleton animation="gradient" :row-col="[{ width: '35%', height: '36px', type: 'rect' }]" />
          </div>
          <div class="msg-skeleton msg-skeleton-bot">
            <t-skeleton animation="gradient" :row-col="[{ width: '70%', height: '16px' }, { width: '90%', height: '16px' }]" />
          </div>
        </div>
        <div class="nexus-chat__body">
          <NativeWatchdogBanner v-if="showWatchdogBanner(run)" class="nexus-chat__banner"
            :can-hint="canSteer(run)" :busy="busy" @acknowledge="acknowledge" @cancel="cancelRun" @hint="sendHint" />

          <t-alert v-if="errorText" theme="error" :message="errorText" class="nexus-chat__alert" />
          <t-alert v-if="streamError" theme="warning" :message="$t('nativeRuns.streamError', { message: streamError })"
            class="nexus-chat__alert" />

          <section v-if="!isWelcome" class="nexus-chat__transcript" aria-live="polite" data-testid="chat-transcript">
            <template v-for="(message, index) in messages" :key="message.id">
              <MessageTimestamp v-if="shouldShowConversationTimestamp(messages, index)" :value="message.created_at" />
              <!-- 用户消息直接复用 WeKnora 的 usermsg（气泡、发送时间与复制）；平台暂无分叉与回滚。 -->
              <div v-if="message.role === 'user'" class="nexus-chat__turn is-user" :data-message-id="message.id">
                <usermsg :content="message.content" :message-id="message.id" :created-at="message.created_at"
                  :session-id="activeSessionId" />
              </div>
              <div v-else class="nexus-chat__turn is-assistant" :data-message-id="message.id">
                <div class="bot_msg">
                  <div class="nexus-chat__markdown" v-html="renderMarkdown(message.content, false)" />
                  <!-- 与 WeKnora botmsg 的 answer-toolbar 一致，悬停时显示；目前只提供复制。 -->
                  <div v-if="message.content" class="answer-toolbar">
                    <t-button size="small" variant="outline" shape="round" :title="$t('agent.copy')"
                      :aria-label="$t('agent.copy')" data-testid="chat-copy-answer" @click.stop="copyAnswer(message.content)">
                      <ChatActionIcon name="copy" />
                    </t-button>
                  </div>
                </div>
              </div>
            </template>

            <!-- 本页提交、尚未写入持久化消息的用户输入：在 Run 结束并重新加载消息前先显示。 -->
            <div v-for="(text, index) in pendingUsers" :key="`pending-${index}`" class="nexus-chat__turn is-user">
              <usermsg :content="text" />
            </div>

            <!-- 当前运行：WeKnora 的智能体时间线组件，输入由 toAgentEventStream 从 Run 事件映射而来。 -->
            <div v-if="liveSession" class="nexus-chat__turn is-assistant is-live" data-testid="chat-live-stream">
              <AgentStreamDisplay class="nexus-chat__stream" :session="liveSession" />
            </div>

            <!-- 与 WeKnora 一致：已提交但尚无流式内容时显示等待指示。 -->
            <div v-if="showGlobalWait" class="chat-global-wait" role="status" :aria-label="$t('chat.thinkingAlt')"
              data-testid="chat-global-wait">
              <span class="chat-global-wait__spinner" aria-hidden="true"></span>
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
        </div>
      </div>
    </div>

    <div class="nexus-chat__composer-wrap">
      <!-- 输入区复用 WeKnora 的 Input-field，nexus-mode 下只保留文本、发送、追加指令与停止。 -->
      <div class="input-container" :class="{ 'is-compact': compact }">
        <transition name="scroll-btn-fade">
          <button v-show="userHasScrolledUp && !isWelcome" type="button" class="scroll-to-bottom-btn"
            :aria-label="$t('nexusChat.scrollToBottom')" data-testid="chat-scroll-bottom" @click="scrollToBottom(true)">
            <t-icon name="chevron-down" size="18px" />
          </button>
        </transition>
        <InputField nexus-mode class="nexus-chat__input" data-testid="chat-composer" :auto-focus="isWelcome"
          :is-replying="isReplying" :can-steer="canSteer(run)"
          @send-msg="onSendMsg" @steer-msg="onSteerMsg" @stop-generation="cancelRun">
          <template #controls>
            <t-select v-if="isWelcome && allowAgentSelect" v-model="selectedAgent" size="small" class="nexus-chat__agent"
              :placeholder="$t('nativeRuns.agentPlaceholder')" :loading="loadingAgents" :options="agentOptions"
              :disabled="agentOptions.length === 0" data-testid="chat-agent-select" />
          </template>
        </InputField>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import {
  createSession as createSessionApi,
  getConversation,
  listAgents,
  listSessions,
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
import usermsg from '@/views/chat/components/usermsg.vue'
import MessageTimestamp from '@/components/chat/MessageTimestamp.vue'
import ChatActionIcon from '@/components/ChatActionIcon.vue'
import { shouldShowConversationTimestamp } from '@/utils/messageTimestamp'
import { copyWithToast } from '@/utils/clipboard'

const { t } = useI18n()
const authStore = useAuthStore()
const route = useRoute()

/**
 * 对话页核心。会话由父组件通过 sessionId 传入，空值即欢迎态；欢迎态发送时先创建会话，
 * 并通过 session-created 通知父组件（路由页据此改写地址，面板据此记录会话）。
 */
const props = withDefaults(defineProps<{
  /** 当前会话；为空时显示欢迎态（尚未创建会话）。 */
  sessionId?: string
  /** 窄容器布局（如侧边面板）：输入区使用紧凑留白。 */
  compact?: boolean
  /** 欢迎态下允许选择智能体（独立对话页）；嵌入场景固定使用默认智能体。 */
  allowAgentSelect?: boolean
}>(), { sessionId: '', compact: false, allowAgentSelect: false })
const emit = defineEmits<{ (e: 'session-created', id: string): void }>()

const activeSessionId = computed(() => props.sessionId)
const isWelcome = computed(() => !activeSessionId.value)
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
/** 当前会话的标题；平台会话没有单独的读取接口，从会话列表中取。 */
const sessionTitleText = ref('')
/** 用户向上滚动离开底部后为 true：此时新内容不再自动滚动，并显示「回到底部」按钮（同 WeKnora）。 */
const userHasScrolledUp = ref(false)
/** 距底部小于该像素数视为仍在底部。 */
const BOTTOM_THRESHOLD = 80
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

const sessionTitle = computed(() => sessionTitleText.value || t('createChat.newSessionTitle'))

/** 已提交、但还没有任何流式事件时显示等待指示（WeKnora 的 showGlobalTypingIndicator）。 */
const showGlobalWait = computed(() => {
  const current = run.value
  if (!current || !isActive(current)) return false
  return native.state.value.events.length === 0
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
    // 从智能体列表「开始对话」进入时，`?agent=<版本 ID>` 预选该智能体（仅限独立对话页）。
    const requested = props.allowAgentSelect && typeof route.query.agent === 'string' ? route.query.agent : ''
    if (requested && agents.value.some(agent => agent.published_version_id === requested)) {
      selectedAgent.value = requested
    } else if (!selectedAgent.value || !agents.value.some(agent => agent.published_version_id === selectedAgent.value)) {
      selectedAgent.value = agents.value[0]?.published_version_id ?? undefined
    }
  } catch (error) {
    errorText.value = messageOf(error, t('nativeRuns.loadError'))
  } finally {
    loadingAgents.value = false
  }
}

/** 读取会话标题；失败时沿用默认标题，不影响对话。 */
async function loadSessionTitle(id: string) {
  const tenant = tenantId.value
  if (!tenant || !id) return
  try {
    const found = (await listSessions(tenant)).find(item => item.id === id)
    if (activeSessionId.value === id) sessionTitleText.value = found?.title || ''
  } catch {
    /* 保留默认标题 */
  }
}

async function openSession() {
  errorText.value = ''
  if (!tenantId.value) {
    errorText.value = t('nativeRuns.noSpace')
    return
  }
  loading.value = true
  userHasScrolledUp.value = false
  void loadSessionTitle(activeSessionId.value)
  try {
    messages.value = await native.loadSession(activeSessionId.value)
  } catch (error) {
    errorText.value = messageOf(error, t('nativeRuns.loadError'))
  } finally {
    loading.value = false
  }
}

/** 运行结束后重新读取持久化的消息，使流式文本与已保存的回答不会同时出现。 */
async function reloadMessages() {
  if (!tenantId.value || !activeSessionId.value) return
  const page = await getConversation(tenantId.value, activeSessionId.value)
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
      sessionTitleText.value = session.title
      pendingUsers.value = [text]
      await native.send(session.id, text)
      emit('session-created', session.id)
    } else {
      pendingUsers.value = [...pendingUsers.value, text]
      await native.send(activeSessionId.value, text)
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

function scrollToBottom(smooth = false) {
  const el = scrollRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  userHasScrolledUp.value = false
}

function handleScroll() {
  const el = scrollRef.value
  if (!el) return
  userHasScrolledUp.value = el.scrollHeight - el.scrollTop - el.clientHeight > BOTTOM_THRESHOLD
}

function copyAnswer(content: string) {
  void copyWithToast(content, 'common.copySuccess', 'common.copyFailed')
}

// 新消息或流式文本增长时保持在底部；用户已向上滚动阅读时不打断（同 WeKnora）。
watch(
  () => [messages.value.length, pendingUsers.value.length, native.state.value.events.length],
  async () => {
    if (userHasScrolledUp.value) return
    await nextTick()
    scrollToBottom()
  },
)

// 用户发送新消息时总是回到底部。
watch(() => pendingUsers.value.length, async (length, previous) => {
  if (length > (previous ?? 0)) {
    await nextTick()
    scrollToBottom()
  }
})

watch(activeSessionId, (id) => {
  // 欢迎页刚创建的会话：Run 已在进行中，保留其流式状态，不做 dispose 与重新加载。
  if (id && String(id) === createdSessionId) return
  native.dispose()
  pendingUsers.value = []
  sessionTitleText.value = ''
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

// 父组件（如侧边面板）通过此方法发送消息：有会话则发到该会话，欢迎态则新建会话。
defineExpose({ sendText })
</script>

<style lang="less" scoped>
@import '../../components/css/chat-scrollbar.less';
// 回答下方工具栏（answer-toolbar）与 WeKnora botmsg 共用。
@import '../../components/css/chat-message-shared.less';
.nexus-chat {
  /* 与 WeKnora 对话页 .chat 一致：整列居中，最窄 400px，由父级控制宽度 */
  --chat-content-inset: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  height: 100%;
  min-height: 0;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  position: relative;
  background: var(--td-bg-color-container);
}


.nexus-chat__header {
  display: flex;
  align-items: center;
  flex: 0 0 var(--app-chat-header-height);
  width: 100%;
  min-width: 0;
  padding: 0 12px 0 var(--chat-content-inset, 20px);
  box-sizing: border-box;
  border-bottom: 1px solid var(--td-component-stroke);
  background: var(--td-bg-color-container);
}


.nexus-chat__scroll {
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 8px 0 0;
  box-sizing: border-box;
  overflow-y: auto;
  overscroll-behavior-y: contain;
  .chat-scrollbar();
}



.nexus-chat__column {
  /* 与 WeKnora .msg_list 一致：最宽 960px，左右各留 --chat-content-inset */
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: calc(960px + 2 * var(--chat-content-inset, 20px));
  width: 100%;
  margin: 0 auto;
  padding: 0 var(--chat-content-inset, 20px);
  box-sizing: border-box;
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
  /* 与 WeKnora .chat_composer / .input-container（非嵌入）一致：底部固定在列内 */
  flex-shrink: 0;
  width: 100%;
  padding: 16px 0 max(8px, env(safe-area-inset-bottom));
  box-sizing: border-box;
  background: var(--td-bg-color-container);
}

.input-container {
  /* 与 WeKnora .input-container（非嵌入）一致 */
  position: relative;
  min-height: 0;
  flex-shrink: 0;
  width: 100%;
  max-width: calc(960px + 2 * var(--chat-content-inset, 20px));
  margin: 0 auto;
  padding: 0 var(--chat-content-inset, 20px);
  box-sizing: border-box;
}

.nexus-chat.is-compact .nexus-chat__composer-wrap {
  padding: 0;
}

.input-container.is-compact {
  max-width: 100%;
  margin: 0;
  padding: 12px 16px 16px;
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
  .nexus-chat__column {
    padding: 0 12px;
  }

  .nexus-chat__agent {
    width: 160px;
  }
}

/* ---- 以下按 WeKnora 对话页样式复制（views/chat/index.vue、creatChat.vue、ChatHeader.vue） ---- */

/* 欢迎态：标题与输入框一起垂直居中（WeKnora .dialogue-wrap / .dialogue-answers）。 */
.nexus-chat.is-welcome:not(.is-compact) {
  justify-content: center;

  .nexus-chat__scroll {
    flex: 0 0 auto;
    overflow: visible;
    padding: 0;
  }

  .nexus-chat__column {
    align-items: center;
    gap: 24px;
  }

  .nexus-chat__composer-wrap {
    padding-top: 24px;
  }
}

.dialogue-title {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--td-text-color-primary);
  font-family: var(--app-font-family);
  font-size: var(--app-text-4xl);
  font-weight: 600;
  text-align: center;
}

.nexus-chat__body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 顶栏标题（WeKnora ChatHeader）。 */
.chat-header {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  max-width: min(520px, calc(100% - 120px));
  min-width: 0;
  box-sizing: border-box;
}

.chat-header__title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  margin: 0;
  padding: 0;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-base);
  font-weight: 500;
  line-height: 20px;
  cursor: default;
}

.chat-header__title-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nexus-chat__status {
  margin-left: 8px;
  flex-shrink: 0;
}

.bot_msg {
  width: 100%;
  min-width: 0;
}

.msg-skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 960px;
  padding: 16px 0;
}

.msg-skeleton-user {
  display: flex;
  justify-content: flex-end;
}

.msg-skeleton-bot {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-left: 4px;
}

.scroll-to-bottom-btn {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  bottom: calc(100% + 8px);
  z-index: 10;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: var(--app-radius-pill);
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--td-text-color-secondary);
  transition: background-color var(--app-motion-base) ease, color var(--app-motion-base) ease, box-shadow var(--app-motion-base) ease;

  &:hover {
    background: var(--td-bg-color-container-hover);
    color: var(--td-text-color-primary);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }

  &:active {
    transform: translateX(-50%) scale(0.92);
  }
}

.scroll-btn-fade-enter-active,
.scroll-btn-fade-leave-active {
  transition: opacity var(--app-motion-base) ease, transform var(--app-motion-base) ease;
}

.scroll-btn-fade-enter-from,
.scroll-btn-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px);
}

.chat-global-wait {
  display: flex;
  align-items: center;
  min-height: 28px;
  padding-left: 4px;
}

.chat-global-wait__spinner {
  width: 12px;
  height: 12px;
  box-sizing: border-box;
  border: 1.5px solid var(--td-component-stroke);
  border-top-color: var(--td-text-color-secondary);
  border-radius: var(--app-radius-pill);
  animation: wk-spin 0.8s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .chat-global-wait__spinner {
    animation: none;
  }
}
</style>
