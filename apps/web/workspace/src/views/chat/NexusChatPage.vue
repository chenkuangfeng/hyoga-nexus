<template>
  <!--
    Platform chat page (/platform/creatChat and /platform/chat/:chatid, and narrow containers in compact mode).
    Structure, components and styles copy WeKnora `views/chat/index.vue` (conversation) and
    `views/creatChat/creatChat.vue` (welcome). Data comes only from the platform Native API.
    Entries without a platform backend stay visible and show "not available yet"
    (openspec 2026-11-04-weknora-chat-dialog, scope change 2026-11-05).
  -->

  <!-- Welcome (WeKnora creatChat): title, suggested questions, composer, centred together. -->
  <div v-if="isWelcome && !compact" class="dialogue-wrap" data-testid="chat-welcome">
    <div class="dialogue-answers">
      <div class="dialogue-title">
        <span data-testid="chat-welcome-title">{{ $t('createChat.title') }}</span>
      </div>
      <t-alert v-if="errorText" theme="error" :message="errorText" class="nexus-chat-alert" />
      <div class="suggested-questions-container has-questions">
        <div class="suggested-questions-inner">
          <div class="suggested-questions-title-row">
            <p class="suggested-questions-caption">
              <span class="suggested-questions-title">{{ $t('chat.suggestedQuestions') }}</span>
              <button type="button" class="suggested-questions-refresh" :title="$t('chat.refreshSuggestedQuestions')"
                :aria-label="$t('chat.refreshSuggestedQuestions')" @click="planned('suggestedQuestions')">
                <t-icon name="refresh" />
              </button>
            </p>
          </div>
          <div class="suggested-questions-grid">
            <div class="suggested-question-card sq-card-visible" data-testid="chat-planned-suggestions"
              @click="planned('suggestedQuestions')">
              <span class="suggested-question-text">{{ $t('nexusChat.suggestionsPlanned') }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="create-chat-composer">
        <InputField nexus-mode data-testid="chat-composer" :auto-focus="true" :is-replying="false" :can-steer="false"
          :nexus-agents="agentOptions" :nexus-agent-id="selectedAgent ?? ''" :nexus-agent-locked="!allowAgentSelect"
          @update:nexus-agent-id="(id: string) => { selectedAgent = id }" @send-msg="onSendMsg" />
      </div>
    </div>
  </div>

  <!-- Conversation (WeKnora views/chat/index.vue). -->
  <div v-else class="chat" :class="{ 'is-embedded': compact }">
    <div v-if="!compact" class="chat-topbar">
      <NexusChatHeader :title="sessionTitleText" :session-id="activeSessionId" @copy-markdown="copyMarkdown" />
      <!-- Nexus: tools allowed for the rest of this session (openspec 2026-11-06-tool-call-hardening 7.3). -->
      <t-popup v-if="toolGrants.length" trigger="click" placement="bottom-right" overlay-class-name="wk-popover">
        <button type="button" class="tool-grants-toggle" :aria-label="$t('nativeRuns.toolGrants.title')">
          <t-icon name="secured" /> {{ toolGrants.length }}
        </button>
        <template #content>
          <div class="tool-grants-panel">
            <p class="tool-grants-title">{{ $t('nativeRuns.toolGrants.title') }}</p>
            <p class="tool-grants-hint">{{ $t('nativeRuns.toolGrants.hint') }}</p>
            <div v-for="grant in toolGrants" :key="grant.id" class="tool-grants-row">
              <span class="tool-grants-name">{{ grant.tool_name }}</span>
              <t-button size="small" variant="text" theme="danger" @click="revokeGrant(grant.id)">
                {{ $t('nativeRuns.toolGrants.revoke') }}
              </t-button>
            </div>
          </div>
        </template>
      </t-popup>
      <div class="sandbox-header-toggle" :class="{ 'after-grants': toolGrants.length }">
        <t-tooltip placement="bottom">
          <template #content>{{ $t('chatHeader.toggleSandboxPanel') }}</template>
          <button type="button" class="sandbox-header-toggle__btn" :aria-label="$t('chatHeader.toggleSandboxPanel')"
            data-testid="chat-planned-sandbox" @click="planned('sandboxPanel')">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <rect x="1.5" y="1.5" width="17" height="17" rx="3" stroke="currentColor" stroke-width="1.2" />
              <line x1="12.5" y1="1.5" x2="12.5" y2="18.5" stroke="currentColor" stroke-width="1.2" />
              <line x1="16" y1="7.5" x2="16" y2="12.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" />
            </svg>
          </button>
        </t-tooltip>
      </div>
    </div>
    <div class="chat_thread" :style="{ '--chat-composer-height': `${composerHeight}px`, '--chat-scrollbar-gutter': `${scrollbarGutter}px` }">
      <div ref="scrollContainer" class="chat_scroll_box" @scroll="handleScroll">
        <div class="chat_scroll_content">
          <div class="msg_list" :class="{ 'is-embedded': compact }" data-testid="chat-transcript" aria-live="polite">
            <t-alert v-if="errorText" theme="error" :message="errorText" class="nexus-chat-alert" />
            <t-alert v-if="streamError" theme="warning" :message="$t('nativeRuns.streamError', { message: streamError })"
              class="nexus-chat-alert" />
            <t-alert v-if="blockedSession" theme="warning" :message="$t('nativeRuns.blocked.message')"
              class="nexus-chat-alert" data-testid="chat-blocked">
              <template #operation>
                <t-button size="small" theme="primary" :loading="releasing" data-testid="chat-blocked-release"
                  @click="releaseBlockedSession">{{ $t('nativeRuns.blocked.release') }}</t-button>
              </template>
            </t-alert>

            <div v-if="loading && rows.length === 0" class="msg-skeleton-list" data-testid="chat-skeleton">
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

            <div v-for="(row, index) in rows" :key="row.id" class="msg-item-wrapper">
              <MessageTimestamp v-if="shouldShowConversationTimestamp(rows, index)" :value="row.created_at" />
              <div v-if="row.role === 'user'" class="message-row" :data-message-id="row.id">
                <usermsg :content="row.content" :session-id="activeSessionId" :message-id="row.id"
                  :created-at="row.created_at" :embedded-mode="compact" :can-fork="!compact" :can-rewind="!compact"
                  @fork="planned('fork')" @rewind="planned('rewind')" />
              </div>
              <div v-else class="message-row" :data-message-id="row.id">
                <botmsg :content="row.content" :session="row" :session-id="activeSessionId" :user-query="userQueryBefore(index)"
                  :is-first-enter="isFirstEnter" :embedded-mode="compact" :can-fork="!compact" :can-rewind="!compact"
                  @scroll-bottom="scrollToBottom()" @fork="planned('fork')"
                  @rewind="planned('rewind')" />
                <KnowledgeCitations v-if="row.citations?.length" :citations="row.citations" />
                <RunArtifactCards v-if="row.run_id && artifactsByRun.get(row.run_id)?.length"
                  :items="artifactsByRun.get(row.run_id)!" />
              </div>
            </div>

            <div v-if="showGlobalWait" class="chat-global-wait" role="status" :aria-label="$t('chat.thinkingAlt')"
              data-testid="chat-global-wait">
              <span class="chat-global-wait__spinner" aria-hidden="true"></span>
            </div>
          </div>
        </div>
      </div>
      <div ref="composerElement" class="chat_composer">
        <div class="input-container" :class="{ 'is-embedded': compact }">
          <transition name="scroll-btn-fade">
            <div v-show="userHasScrolledUp" class="scroll-to-bottom-btn" role="button" tabindex="0"
              :aria-label="$t('nexusChat.scrollToBottom')" data-testid="chat-scroll-bottom"
              @click="scrollToBottom(true)" @keydown.enter="scrollToBottom(true)">
              <t-icon name="chevron-down" size="18px" />
            </div>
          </transition>
          <PendingPromptDock :embedded-mode="compact" />
          <InputField nexus-mode compact data-testid="chat-composer" :auto-focus="isWelcome" :is-replying="isReplying"
            :can-steer="canSteer(run)" :embedded-mode="compact"
            :nexus-agents="agentOptions" :nexus-agent-id="isWelcome ? (selectedAgent ?? '') : sessionAgentVersion"
            :nexus-agent-locked="!isWelcome || !allowAgentSelect"
            @update:nexus-agent-id="(id: string) => { selectedAgent = id }"
            @send-msg="onSendMsg" @steer-msg="onSteerMsg" @stop-generation="cancelRun" />
        </div>
      </div>
      <div v-if="!compact" class="chat_overlays">
        <ChatQuestionMinimap :scroll-container="scrollContainer" :messages="rows" @jump="jumpToQuestion" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import KnowledgeCitations from '@/components/knowledge/KnowledgeCitations.vue'
import RunArtifactCards from '@/views/chat/components/RunArtifactCards.vue'
/**
 * Conversation core. The session comes from the parent as `sessionId`; empty means the welcome state.
 * Sending from the welcome state creates the session first and emits `session-created`.
 *
 * Rows are rebuilt from persisted messages plus each Run's events (`buildChatRows`), so finished answers
 * show the same agent timeline as the live one. Approvals and questions use WeKnora's cards through
 * `provideNexusChatActions`; entries without a platform backend call `planned()`.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  createSession as createSessionApi,
  getConversation,
  listAgents,
  listPendingApprovals,
  listRunEvents,
  listSessions,
  resolveApproval,
  listToolGrants,
  revokeToolGrant,
  type ToolGrant,
  type AgentView,
  type ConversationMessage,
  type RunEvent,
} from '@nexus-web/core/api/native-runs'
import { useNativeRun } from '@/composables/useNativeRun'
import { provideNexusChatActions } from '@/composables/nexusChatActions'
import { archiveMemoryEntry, listPendingDraftIds, reviewMemoryDraft } from '@nexus-web/core/api/nexus-memory'
import { providePromptDock } from '@/composables/usePromptDock'
import { canSteer, failureCode, isActive, isTerminal } from '@/views/native/nativeRunState'
import InputField from '@/components/Input-field.vue'
import NexusChatHeader from '@/components/NexusChatHeader.vue'
import MessageTimestamp from '@/components/chat/MessageTimestamp.vue'
import ChatQuestionMinimap from '@/components/chat/ChatQuestionMinimap.vue'
import usermsg from '@/views/chat/components/usermsg.vue'
import botmsg from '@/views/chat/components/botmsg.vue'
import PendingPromptDock from '@/views/chat/components/PendingPromptDock.vue'
import { shouldShowConversationTimestamp } from '@/utils/messageTimestamp'
import { listSessionArtifacts, type ArtifactLibraryItem } from '@nexus-web/core/api/artifacts'
import { groupArtifactsByRun } from '@/utils/runArtifacts'
import { copyWithToast } from '@/utils/clipboard'
import { deriveSessionTitle } from '@/utils/nexusChatTitle'
import { summarizeAskUserAnswer, type AskUserQuestion } from '@/utils/askUser'
import { buildChatRows, runsNeedingEvents, transcriptMarkdown, type ChatRow } from '@/utils/nexusChatTranscript'

const { t } = useI18n()
const authStore = useAuthStore()
const route = useRoute()

const props = withDefaults(defineProps<{
  /** Current session; empty shows the welcome state. */
  sessionId?: string
  /** Narrow container: WeKnora's embedded layout, no header or minimap. */
  compact?: boolean
  /** Allow choosing the agent in the welcome state (standalone page). */
  allowAgentSelect?: boolean
}>(), { sessionId: '', compact: false, allowAgentSelect: false })
const emit = defineEmits<{ (e: 'session-created', id: string): void }>()

/** Concurrent event reads when rebuilding the timelines of a session's finished Runs. */
const EVENT_READ_CONCURRENCY = 4
/** Distance from the bottom still treated as "at the bottom" (WeKnora SCROLL_BOTTOM_THRESHOLD). */
const SCROLL_BOTTOM_THRESHOLD = 80

const activeSessionId = computed(() => props.sessionId)
const isWelcome = computed(() => !activeSessionId.value)
const tenantId = computed(() => authStore.effectiveTenantId)
const native = useNativeRun(() => tenantId.value)

const messages = ref<ConversationMessage[]>([])
const eventsByRun = ref(new Map<string, RunEvent[]>())
const approvalArgs = ref(new Map<string, Record<string, unknown>>())
const loading = ref(false)
const errorText = ref('')
const agents = ref<AgentView[]>([])
const selectedAgent = ref<string | undefined>(undefined)
const pendingUsers = ref<string[]>([])
const sessionTitleText = ref('')
/** Agent version the open session is bound to; shown on the composer's agent button. */
const sessionAgentVersion = ref('')
/** WeKnora: true on entering a session (history renders without the typewriter), false after sending. */
const isFirstEnter = ref(true)
const userHasScrolledUp = ref(false)
const scrollContainer = ref<HTMLElement | null>(null)
const composerElement = ref<HTMLElement | null>(null)
const composerHeight = ref(0)
const scrollbarGutter = ref(0)
/** Session created from the welcome state; the route change to it must not reload over the live Run. */
let createdSessionId = ''

const run = computed(() => native.state.value.run)
const streamError = computed(() => native.streamError.value)
const blockedSession = computed(() => native.blocked.value)
const releasing = ref(false)

/** Release the session a lost worker's Run left blocked; the interrupted Run is not run again. */
async function releaseBlockedSession() {
  releasing.value = true
  try {
    await native.releaseBlocked()
    MessagePlugin.success(t('nativeRuns.blocked.released'))
  } catch (error) {
    MessagePlugin.error(t('nativeRuns.blocked.failed', { message: messageOf(error, '') }))
  } finally {
    releasing.value = false
  }
}

const rows = computed<ChatRow[]>(() => {
  const current = run.value
  const live = current ? {
    id: current.id,
    status: current.status,
    events: native.state.value.events,
    options: { approvalArgs: approvalArgs.value },
  } : null
  return buildChatRows(messages.value, eventsByRun.value, pendingUsers.value, live, { failureMessage })
})

// The prompt dock (WeKnora PendingPromptDock) reads a reactive message list.
const dockRows = reactive<ChatRow[]>([])
watchEffect(() => { dockRows.splice(0, dockRows.length, ...rows.value) })
providePromptDock(dockRows as unknown as Record<string, unknown>[])

const agentOptions = computed(() => agents.value.map(agent => ({
  id: agent.published_version_id as string,
  name: agent.name,
  description: agent.description,
})))

const isReplying = computed(() => isActive(run.value))

/** WeKnora shows a run-level error as the answer text; the code identifies the cause. */
function failureMessage(code: string): string {
  return code ? t('nativeRuns.failure', { code }) : t('chat.processError')
}
/** WeKnora showGlobalTypingIndicator: submitted, nothing streamed yet. */
const showGlobalWait = computed(() => isActive(run.value) && native.state.value.events.length === 0)

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const data = error as { message?: unknown; error?: unknown } | null
  if (data && typeof data.message === 'string') return data.message
  if (data && typeof data.error === 'string') return data.error
  return fallback
}

/** Entries kept from WeKnora whose platform backend does not exist yet. */
function planned(feature: string) {
  void feature
  MessagePlugin.info({ content: t('nexusChat.planned'), duration: 2000 })
}

function userQueryBefore(index: number): string {
  for (let i = index - 1; i >= 0; i--) {
    const row = rows.value[i]
    if (row.role === 'user') return row.content
  }
  return ''
}

// ---- data loading -----------------------------------------------------------------------------

async function loadAgents() {
  const tenant = tenantId.value
  if (!tenant) return
  try {
    agents.value = (await listAgents(tenant)).filter(agent => agent.published_version_id !== null)
    // From the agent list's "start chat": `?agent=<version id>` preselects that agent (standalone page only).
    const requested = props.allowAgentSelect && typeof route.query.agent === 'string' ? route.query.agent : ''
    if (requested && agents.value.some(agent => agent.published_version_id === requested)) {
      selectedAgent.value = requested
    } else if (!selectedAgent.value || !agents.value.some(agent => agent.published_version_id === selectedAgent.value)) {
      selectedAgent.value = agents.value[0]?.published_version_id ?? undefined
    }
  } catch (error) {
    errorText.value = messageOf(error, t('nativeRuns.loadError'))
  }
}

async function loadSessionTitle(id: string) {
  const tenant = tenantId.value
  if (!tenant || !id) return
  try {
    const found = (await listSessions(tenant)).find(item => item.id === id)
    if (activeSessionId.value === id) {
      sessionTitleText.value = found?.title || ''
      sessionAgentVersion.value = found?.agent_version_id || ''
    }
  } catch {
    /* keep the default title */
  }
}

/** Read the events of finished Runs, a few at a time; a failed read leaves that answer as plain text. */
async function loadRunEvents(sessionId: string) {
  const tenant = tenantId.value
  if (!tenant) return
  const queue = runsNeedingEvents(messages.value, new Set(eventsByRun.value.keys()), run.value?.id ?? null)
  const worker = async () => {
    for (let id = queue.shift(); id; id = queue.shift()) {
      try {
        const events = await listRunEvents(tenant, id)
        if (activeSessionId.value !== sessionId) return
        eventsByRun.value = new Map(eventsByRun.value).set(id, events)
      } catch {
        /* the row keeps its persisted text */
      }
    }
  }
  await Promise.all(Array.from({ length: EVENT_READ_CONCURRENCY }, worker))
}

/** Files the session's Runs left under /outputs (openspec 2026-11-07-tool-expansion 4.6), shown under their answers. */
const sessionArtifacts = ref<ArtifactLibraryItem[]>([])
const artifactsByRun = computed(() => groupArtifactsByRun(sessionArtifacts.value))

async function loadArtifacts(sessionId: string) {
  try {
    const items = await listSessionArtifacts(sessionId)
    if (activeSessionId.value === sessionId) sessionArtifacts.value = items
  } catch {
    /* the answer is complete without its file cards; the artifacts page still lists them */
  }
}

async function openSession() {
  errorText.value = ''
  if (!tenantId.value) {
    errorText.value = t('nativeRuns.noSpace')
    return
  }
  const id = activeSessionId.value
  loading.value = true
  userHasScrolledUp.value = false
  isFirstEnter.value = true
  eventsByRun.value = new Map()
  approvalArgs.value = new Map()
  sessionArtifacts.value = []
  void loadArtifacts(id)
  void loadSessionTitle(id)
  void loadAgents()
  try {
    messages.value = await native.loadSession(id)
    if (run.value?.status === 'waiting_approval') void loadApprovals()
    void loadRunEvents(id)
  } catch (error) {
    errorText.value = messageOf(error, t('nativeRuns.loadError'))
  } finally {
    loading.value = false
  }
}

/** After a Run ends: keep its events for the timeline and reload the persisted messages. */
async function settleRun() {
  const current = run.value
  if (!tenantId.value || !activeSessionId.value || !current) return
  eventsByRun.value = new Map(eventsByRun.value).set(current.id, [...native.state.value.events])
  const page = await getConversation(tenantId.value, activeSessionId.value)
  messages.value = page.messages
  pendingUsers.value = []
  // The worker registers a Run's outputs before it finishes, so they exist by now.
  void loadArtifacts(activeSessionId.value)
}

/** Approval arguments are only exposed to the Run owner through the approvals API. */
async function loadApprovals() {
  const current = run.value
  if (!tenantId.value || !current) return
  try {
    const pending = await listPendingApprovals(tenantId.value, current.id)
    const next = new Map(approvalArgs.value)
    for (const item of pending) next.set(item.id, item.arguments)
    approvalArgs.value = next
  } catch {
    /* the card shows without arguments */
  }
}

// ---- sending and run actions ------------------------------------------------------------------

async function sendText(text: string) {
  if (!tenantId.value) return
  errorText.value = ''
  isFirstEnter.value = false
  try {
    if (isWelcome.value) {
      if (!selectedAgent.value) {
        MessagePlugin.warning(t('nexusChat.needAgent'))
        return
      }
      const session = await createSessionApi(tenantId.value, selectedAgent.value, deriveSessionTitle(text))
      createdSessionId = session.id
      sessionTitleText.value = session.title
      sessionAgentVersion.value = session.agent_version_id
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

/** A message sent while running is a steer for the current Run, shown as a pending user message. */
const onSteerMsg = (text: string) => {
  pendingUsers.value = [...pendingUsers.value, text]
  void sendHint(text)
}

async function act(action: () => Promise<void>, fallback: string) {
  try {
    await action()
  } catch (error) {
    MessagePlugin.error(messageOf(error, fallback))
  }
}

const cancelRun = () => act(() => native.cancel(), t('nativeRuns.loadError'))
const sendHint = (content: string) => act(async () => {
  await native.steer(content)
  MessagePlugin.success(t('nativeRuns.hintSent'))
}, t('nativeRuns.sendError'))

function promptRequest(pendingId: string): AskUserQuestion {
  for (const row of rows.value) {
    if (row.role !== 'assistant') continue
    for (const event of row.agentEventStream) {
      if (event.type === 'agent_prompt_required' && event.pending_id === pendingId) return event.request as AskUserQuestion
    }
  }
  return { question: '' } as AskUserQuestion
}
/** Pending draft ids of the caller (memory draft cards); reset after a review so the next read is fresh. */
let pendingDrafts: Promise<Set<string>> | null = null

/** Session grants of the open conversation (tool-call-hardening E); reloaded on session change and after an approval. */
const toolGrants = ref<ToolGrant[]>([])

async function loadToolGrants() {
  const tenant = tenantId.value, session = activeSessionId.value
  if (!tenant || !session) { toolGrants.value = []; return }
  try {
    const grants = await listToolGrants(tenant, session)
    if (activeSessionId.value === session) toolGrants.value = grants
  } catch {
    toolGrants.value = []
  }
}

async function revokeGrant(grantId: string) {
  const tenant = tenantId.value, session = activeSessionId.value
  if (!tenant || !session) return
  try {
    await revokeToolGrant(tenant, session, grantId)
    MessagePlugin.success(t('nativeRuns.toolGrants.revoked'))
  } catch (error) {
    MessagePlugin.error(error instanceof Error && error.message ? error.message : t('nativeRuns.loadError'))
  }
  await loadToolGrants()
}

watch(() => activeSessionId.value, () => { void loadToolGrants() }, { immediate: true })

provideNexusChatActions({
  async resolveApproval(pendingId, decision, args, rememberForSession) {
    const current = run.value
    if (!tenantId.value || !current) throw new Error(t('nativeRuns.loadError'))
    await resolveApproval(tenantId.value, current.id, pendingId, decision === 'approve', args, rememberForSession)
    if (rememberForSession) void loadToolGrants()
    await native.resume()
  },
  async answerPrompt(pendingId, response) {
    const text = response.declined ? t('agentStream.askUser.declinedTag')
      : summarizeAskUserAnswer(promptRequest(pendingId), response)
    await native.answerInput(text)
  },
  planned,
  async reviewMemoryDraft(draftId, approve, title) {
    if (!tenantId.value) throw new Error(t('nativeRuns.loadError'))
    try {
      const result = await reviewMemoryDraft(tenantId.value, draftId, approve, title)
      pendingDrafts = null
      return result.status
    } catch (error) {
      if ((error as { status?: number })?.status === 409) return 'handled'
      throw error
    }
  },
  async isMemoryDraftPending(draftId) {
    if (!tenantId.value) return null
    try {
      // One request serves every card rendered together; a draft proposed after the last read refetches.
      if (!pendingDrafts || !(await pendingDrafts).has(draftId)) pendingDrafts = listPendingDraftIds(tenantId.value)
      return (await pendingDrafts).has(draftId)
    } catch {
      pendingDrafts = null
      return null
    }
  },
  async forgetMemory(entryId) {
    if (!tenantId.value) throw new Error(t('nativeRuns.loadError'))
    await archiveMemoryEntry(tenantId.value, entryId)
  },
})

function copyMarkdown() {
  const markdown = transcriptMarkdown(sessionTitleText.value || t('createChat.newSessionTitle'), rows.value,
    { user: t('nativeRuns.user'), assistant: t('nativeRuns.assistant') })
  void copyWithToast(markdown, 'common.copySuccess', 'common.copyFailed')
}

// ---- scrolling (WeKnora index.vue) ------------------------------------------------------------

function scrollToBottom(smooth = false) {
  const el = scrollContainer.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  userHasScrolledUp.value = false
}

function handleScroll() {
  const el = scrollContainer.value
  if (!el) return
  userHasScrolledUp.value = el.scrollHeight - el.scrollTop - el.clientHeight > SCROLL_BOTTOM_THRESHOLD
}

function jumpToQuestion(id: string) {
  const root = scrollContainer.value
  if (!root || !id) return
  const el = root.querySelector(`[data-message-id="${CSS.escape(id)}"]`)
  if (!el) return
  const offset = el.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop
  userHasScrolledUp.value = root.scrollHeight - offset >= root.clientHeight + SCROLL_BOTTOM_THRESHOLD
  el.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

/** The composer floats over the thread (WeKnora); its height pads the scroll content. */
let composerObserver: ResizeObserver | null = null
function measureLayout() {
  composerHeight.value = composerElement.value?.offsetHeight ?? 0
  const el = scrollContainer.value
  scrollbarGutter.value = el ? el.offsetWidth - el.clientWidth : 0
}
watch(composerElement, (el, previous) => {
  if (previous && composerObserver) composerObserver.unobserve(previous)
  if (!el || typeof ResizeObserver === 'undefined') return
  composerObserver ??= new ResizeObserver(measureLayout)
  composerObserver.observe(el)
  measureLayout()
})

// Follow new content unless the user scrolled up to read (WeKnora).
watch(() => [rows.value.length, native.state.value.events.length], async () => {
  if (userHasScrolledUp.value) return
  await nextTick()
  scrollToBottom()
})
watch(() => pendingUsers.value.length, async (length, previous) => {
  if (length > (previous ?? 0)) {
    await nextTick()
    scrollToBottom()
  }
})

// ---- lifecycle --------------------------------------------------------------------------------

watch(() => run.value?.status, (status, previous) => {
  if (!status || status === previous) return
  if (status === 'waiting_approval') void loadApprovals()
  if (previous && (status === 'failed' || status === 'interrupted')) {
    // WeKnora reportError: a toast next to the error text in the answer.
    MessagePlugin.error(failureMessage(failureCode(run.value) ?? ''))
  }
  if (previous && isTerminal(run.value)) {
    settleRun().catch(() => { /* keep current rows and pending inputs */ })
  }
})

watch(activeSessionId, (id) => {
  // A session just created from the welcome state already has its Run streaming.
  if (id && String(id) === createdSessionId) return
  native.dispose()
  pendingUsers.value = []
  sessionTitleText.value = ''
  sessionAgentVersion.value = ''
  if (!id) {
    messages.value = []
    eventsByRun.value = new Map()
    sessionArtifacts.value = []
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
onBeforeUnmount(() => {
  native.dispose()
  composerObserver?.disconnect()
})

// Parent containers send through this: to the session, or create one from the welcome state.
defineExpose({ sendText })
</script>

<!-- Copied from WeKnora views/chat/index.vue -->
<style lang="less" scoped>
@import '../../components/css/chat-scrollbar.less';
.chat {
    // 水平方向不留 padding，让滚动条贴到内容区最右缘；
    // 消息列与输入列各自用 --chat-content-inset 做左右对称的留白（窄屏时才可见）。
    padding: 0;
    --chat-content-inset: 20px;
    box-sizing: border-box;
    flex: 1;
    // The parent .platform-route-outlet is a flex column with min-height:0
    // and overflow:hidden — we also need min-height:0 here so that our
    // own flex:1 child (.chat_thread) can shrink below its content height.
    min-height: 0;
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    max-width: 100%;
    min-width: 400px;

    &.is-embedded {
        max-width: 100%;
        min-width: 100%;
        padding: 0;
        overflow-x: hidden;
    }

    &:not(.is-embedded) {
        @media (min-width: 960px) {
            transition: padding-right var(--app-motion-slow) cubic-bezier(0.22, 0.61, 0.36, 1);
        }
    }

    &.has-references-panel:not(.is-embedded) {
        @media (min-width: 960px) {
            padding-right: var(--references-panel-width, 420px);
            box-sizing: border-box;

            .chat_scroll_box {
                padding-top: 0;
            }
        }
    }

    // 沙箱可视化右侧面板：宽度可拖拽调整（--sandbox-panel-width 由
    // composable 持久化），聊天区 padding 跟随面板宽度让位。
    &.has-sandbox-panel:not(.is-embedded) {
        @media (min-width: 960px) {
            padding-right: var(--sandbox-panel-width, 420px);
            box-sizing: border-box;
        }
    }

    &.has-sandbox-panel.has-references-panel:not(.is-embedded) {
        @media (min-width: 1400px) {
            padding-right: calc(var(--references-panel-width, 420px) + var(--sandbox-panel-width, 420px));
        }

        @media (max-width: 1399.98px) and (min-width: 960px) {
            padding-right: var(--sandbox-panel-width, 420px);
        }
    }

    &.is-embedded :deep(.answers-input) {
        position: relative;
        transform: translateX(0);
        width: 100%;
        left: 0;
        bottom: auto;
        display: flex;
        justify-content: center;
    }

    &.is-embedded :deep(.control-bar) {
        justify-content: flex-end;
    }

    &:not(.is-embedded) :deep(.answers-input) {
        position: static;
        transform: translateX(0);

        .t-textarea__inner {
            width: 100% !important;
        }
    }

    &.is-embedded :deep(.answers-input) .t-textarea__inner {
        width: 100% !important;
    }
}

.chat-child-detail { flex: 1; min-height: 0; width: 100%; overflow: hidden; }

.chat_thread {
    position: relative;
    flex: 1;
    min-height: 0;
    width: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.chat-topbar {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: 0 0 var(--app-chat-header-height);
    width: 100%;
    min-width: 0;
    padding: 0 12px 0 var(--chat-content-inset, 20px);
    box-sizing: border-box;
    border-bottom: 1px solid var(--td-component-stroke);
    background: var(--td-bg-color-container);
}

.sandbox-header-toggle {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    margin-left: auto;

    &.after-grants {
        margin-left: 8px;
    }
}

.tool-grants-toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
    padding: 0 6px;
    height: 24px;
    border: none;
    border-radius: var(--app-radius-sm);
    background: transparent;
    color: var(--td-text-color-secondary);
    cursor: pointer;

    &:hover,
    &:focus-visible {
        background: var(--td-bg-color-container-hover);
        color: var(--td-text-color-primary);
    }
}

.tool-grants-panel {
    min-width: 220px;
    max-width: 320px;
    padding: 8px 4px;
}

.tool-grants-title {
    margin: 0 0 4px;
    font-weight: 500;
}

.tool-grants-hint {
    margin: 0 0 8px;
    font-size: var(--app-text-sm);
    color: var(--td-text-color-secondary);
}

.tool-grants-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
}

.tool-grants-name {
    font-family: var(--app-font-mono, monospace);
    font-size: var(--app-text-md);
}

.sandbox-header-toggle__btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 0;
    border-radius: var(--app-radius-sm);
    color: var(--td-text-color-placeholder);
    background: transparent;
    cursor: pointer;
    transition: background-color var(--app-motion-fast) ease, color var(--app-motion-fast) ease;

    &:hover {
        color: var(--td-text-color-primary);
        background: var(--td-bg-color-container-hover);
    }

    &:active {
        background: var(--td-bg-color-container-active);
    }
}

.chat_scroll_box {
    flex: 1;
    min-height: 0;
    width: 100%;
    padding: 8px 0 0;
    box-sizing: border-box;
    overflow-y: auto;
    // Keep native message bounce without chaining scroll to the outer page.
    overscroll-behavior-y: contain;
    scroll-padding-bottom: var(--chat-composer-height, 0px);
    .chat-scrollbar();
}

// Keep the full-height message scrollbar and reserve space below the last
// message for the composer, which sits outside the bouncing scroll viewport.
.chat_scroll_content {
    display: flex;
    flex-direction: column;
    min-height: 100%;

    // Use an in-flow spacer so the content ResizeObserver also detects composer
    // height changes and keeps the last message visible when following replies.
    &::after {
        content: '';
        flex: 0 0 var(--chat-composer-height, 0px);
    }
}

.chat_composer {
    position: absolute;
    bottom: 0;
    left: 0;
    right: var(--chat-scrollbar-gutter, 0px);
    z-index: 12;
    padding: 16px 0 max(8px, env(safe-area-inset-bottom));
    background: var(--td-bg-color-container);
}

.is-embedded .chat_composer {
    padding: 0;
}

.chat_overlays {
    position: absolute;
    inset: 0 0 var(--chat-composer-height, 0px);
    pointer-events: none;

    :deep(.browser-task-preview) {
        pointer-events: auto;
    }
}

.scroll-to-bottom-btn {
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
    bottom: calc(100% + 8px);
    z-index: 10;
    width: 32px;
    height: 32px;
    border-radius: 50%;
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

@keyframes contentFadeIn {
    from {
        opacity: 0;
        transform: translateY(6px);
    }

    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.msg-skeleton-list {
    display: flex;
    flex-direction: column;
    gap: 20px;
    max-width: 960px;
    padding: 16px 0;
    animation: contentFadeIn 0.3s ease-out;
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

.input-container {
    min-height: 0;
    flex-shrink: 0;
    margin: 0 auto;
    width: 100%;
    max-width: 960px;
    box-sizing: border-box;
    position: relative;

    &:not(.is-embedded) {
        padding: 0 var(--chat-content-inset, 20px);
        max-width: calc(960px + 2 * var(--chat-content-inset, 20px));
    }

    &.is-embedded {
        max-width: 100%;
        width: 100%;
        margin: 0;
        padding: 12px 16px 16px;
        min-height: auto;
        box-sizing: border-box;
        overflow-x: clip;
    }
}

.automation-session-notice {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 16px 0;
    color: var(--td-text-color-secondary);
    font-size: var(--app-text-sm);
    line-height: 1.6;

    > .t-icon { flex-shrink: 0; }
}

.msg_list {
    display: flex;
    flex-direction: column;
    gap: 16px;
    max-width: 960px;
    flex: 1;
    margin: 0 auto;
    width: 100%;
    box-sizing: border-box;

    &:not(.is-embedded) {
        padding: 0 var(--chat-content-inset, 20px);
        max-width: calc(960px + 2 * var(--chat-content-inset, 20px));
    }

    // Matches the composer's inset, and keeps text clear of the scrollbar,
    // which overlays content where the platform uses overlay scrollbars.
    &.is-embedded {
        padding: 0 16px;
    }

    /*
      给每条消息加 layout/style containment：
      - 一条消息的内部布局变化不再让浏览器去 invalidate 整个文档，
        这是修掉"hover 到 session 列表也变白"那个问题的关键。
      - 不要再用 content-visibility: auto / contain-intrinsic-size：
        agent 消息真实高度差异巨大（几百 ~ 数千 px），估的占位高度会让消息进入视口时
        反复发生"占位 -> 真实高度"的大幅 layout shift + 首次 paint 滞后，
        反而在向上滚动时制造"未画完"的白屏闪烁。
        当前 handleMsgList 全流程 ~50ms，根本无需跳过渲染，老老实实正常渲染最稳。
      - 不开 contain: paint：AgentStreamDisplay 里有 tooltip / popover 等会溢出的浮层，
        paint containment 会把它们裁掉。
    */
    .msg-item-wrapper {
        contain: layout style;
        &.is-empty-segment { display: none; }
        &.is-steer-prefix { margin-bottom: -4px; }
    }

    .message-row {
        display: flex;
        flex-direction: column;
        width: 100%;

    }

    .botanswer_laoding_gif {
        width: 24px;
        height: 18px;
        margin-left: 16px;
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
        border-radius: 50%;
        animation: wk-spin 0.8s linear infinite;
    }
}

@media (prefers-reduced-motion: reduce) {
    .chat-global-wait__spinner {
        animation: none;
    }
}

@import '../../components/css/suggested-questions.less';

.suggested-questions-container {
    transition: min-height var(--app-motion-slow) @suggested-ease;
}

.suggested-questions-inner {
    animation: contentFadeIn 0.3s ease-out;
}

.sq-fade-enter-active,
.sq-fade-leave-active {
    transition: opacity var(--app-motion-slow) @suggested-ease;
}

.sq-fade-enter-from,
.sq-fade-leave-to {
    opacity: 0;
}
</style>

<style lang="less">
.chat-rewind-popconfirm {
    .t-popconfirm__content {
        width: 280px;
        max-width: calc(100vw - 24px);
        padding: 14px 16px 12px;
        box-sizing: border-box;
    }

    .t-popconfirm__body {
        gap: 8px;
    }

    .t-popconfirm__body > .t-icon {
        flex-shrink: 0;
        margin: 0;
        padding: 3px 0 0;
        font-size: var(--app-text-xl);
    }

    .t-popconfirm__inner {
        flex: 1;
        min-width: 0;
        max-width: none;
        white-space: normal;
    }

    .chat-rewind-confirm__title {
        font-size: var(--app-text-base);
        font-weight: 500;
        line-height: 22px;
        color: var(--td-text-color-primary);
    }

    .chat-rewind-confirm__body {
        margin-top: 2px;
        font-size: var(--app-text-md);
        line-height: 20px;
        color: var(--td-text-color-secondary);
    }

    .t-popconfirm__buttons {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        margin-top: 12px;

        .t-popconfirm__confirm {
            margin-left: 0;
        }
    }
}
</style>

<!-- Copied from WeKnora views/creatChat/creatChat.vue -->
<style lang="less" scoped>
.dialogue-wrap {
    flex: 1;
    display: flex;
    justify-content: center;
    align-items: center;
    // position: relative;
}

.dialogue-answers {
    display: flex;
    flex-flow: column;
    align-items: center;
    width: 100%;
    max-width: 960px;
    gap: 24px;

    :deep(.answers-input) {
        position: static;
        transform: translateX(0);
    }
}

.create-chat-composer {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    width: 100%;
}

.project-dir-bar {
    display: flex;
    align-items: center;
    gap: 4px;
    width: 100%;
    max-width: 960px;
    padding: 0;
    box-sizing: border-box;
}

.project-dir-bar__btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 100%;
    height: 28px;
    padding: 0 10px;
    border: 0.5px solid var(--td-component-border);
    border-radius: var(--app-radius-md);
    background: var(--td-bg-color-container);
    color: var(--td-text-color-secondary);
    font-size: var(--app-text-sm);
    cursor: pointer;
}

.project-dir-bar__btn.is-bound {
    color: var(--td-text-color-primary);
}

.project-dir-bar__btn.is-picking,
.project-dir-bar__btn:disabled {
    cursor: default;
    opacity: 0.75;
}

.project-dir-bar__name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.project-dir-bar__clear {
    flex: 0 0 auto;
    border: none;
    background: transparent;
    padding: 0 4px;
    color: var(--td-text-color-placeholder);
    font-size: var(--app-text-base);
    line-height: 1;
    cursor: pointer;
}

.dialogue-title {
    display: flex;
    color: var(--td-text-color-primary);
    font-family: var(--app-font-family);
    font-size: var(--app-text-4xl);
    font-weight: 600;
    align-items: center;
    margin-bottom: 0;

    .icon {
        display: flex;
        width: 32px;
        height: 32px;
        justify-content: center;
        align-items: center;
        border-radius: var(--app-radius-sm);
        background: var(--td-bg-color-container);
        box-shadow: var(--td-shadow-1);
        margin-right: 12px;

        .logo_img {
            height: 24px;
            width: 24px;
        }
    }
}

@import '../../components/css/suggested-questions.less';

@keyframes skeletonFadeIn {
    from {
        opacity: 0;
    }

    to {
        opacity: 1;
    }
}

.suggested-questions-container {
    max-width: 960px;
    margin: 0;
    padding: 0 16px;
    transition: height var(--app-motion-slow) @suggested-ease;
}

.suggested-questions-inner {
    animation: skeletonFadeIn 0.3s ease-out;
}

.sq-slide-fade-enter-active {
    transition: opacity var(--app-motion-slow) @suggested-ease, transform var(--app-motion-slow) @suggested-ease;
}

.sq-slide-fade-leave-active {
    transition: opacity var(--app-motion-fast) cubic-bezier(0.4, 0, 1, 1),
        transform var(--app-motion-fast) cubic-bezier(0.4, 0, 1, 1);
}

.sq-slide-fade-enter-from {
    opacity: 0;
    transform: translateY(10px);
}

.sq-slide-fade-leave-to {
    opacity: 0;
    transform: translateY(-4px);
}

.suggested-question-card {
    opacity: 0;
    transform: translateY(8px) scale(0.97);
    transition:
        opacity var(--app-motion-slow) @suggested-ease,
        transform var(--app-motion-slow) @suggested-ease,
        background var(--app-motion-base) @suggested-ease,
        border-color var(--app-motion-slow) @suggested-ease,
        box-shadow var(--app-motion-slow) @suggested-ease;

    &.sq-card-skeleton {
        opacity: 1;
        transform: none;
    }

    &.sq-card-visible {
        opacity: 1;
        transform: translateY(0) scale(1);
    }

    &:not(.sq-card-skeleton):active {
        transform: scale(0.98);
    }

    &.sq-card-visible:active {
        transform: scale(0.98);
    }
}
</style>

<style lang="less" scoped>
/* Request errors (load or stream failures) shown above the messages. */
.nexus-chat-alert {
  width: 100%;
}

</style>
