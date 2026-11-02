<script setup lang="ts">
/**
 * Conversation page. Layout follows WeKnora's chat: a title bar, the run timeline, and a composer.
 * Sessions are chosen in the sidebar. 新对话 starts a blank draft; the session is created on the first send.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import ModelBranchControls from '../../components/ModelBranchControls.vue'
import MemorySnapshotControl from '../../components/MemorySnapshotControl.vue'
import RuntimeControls from '../../components/RuntimeControls.vue'
import { useConversation } from '../../composables/useConversation'
import { workspace } from '../../stores/workspace'
import ChatTimeline from './ChatTimeline.vue'

const chat = useConversation()
const route = useRoute(), router = useRouter()
const { t, te } = useI18n()
const { agents, sessions, tenant, sessionId, versionId, timeline, stats, run, pendingInput,
  error, loading, submitting, connection, cancelling, active, queueLabel } = chat
const prompt = ref(''), answer = ref('')
const tools = ref(false)

// The URL (/chat/:sessionId) is the source of the open session. Opening a session from the sidebar
// changes the route; the composable's state follows it, and the route follows the composable when a
// session is opened or created here.
onMounted(() => chat.initialize(String(route.params.sessionId || '')))
watch(() => workspace.tenantId, id => { if (id) void chat.selectTenant(id) })
watch(() => route.params.sessionId, id => { const value = String(id || ''); if (value && value !== sessionId.value) void chat.openSession(value) })
watch(sessionId, id => { if (id && route.params.sessionId !== id) void router.replace(`/chat/${id}`) })
watch(sessions, list => { workspace.sessions = list }, { deep: true })
// 新对话 from the sidebar: blank draft, and the URL goes back to /chat.
watch(() => workspace.newChatTick, () => { chat.startDraft(); prompt.value = ''; answer.value = '' })

const title = computed(() => {
  if (!sessionId.value) return t('shell.newChat')
  const current = sessions.value.find(row => row.id === sessionId.value)
  return current?.title || t('chat.untitledSession')
})
const statusText = computed(() => {
  if (cancelling.value) return t('chat.stopping')
  if (queueLabel.value) return queueLabel.value
  if (run.value) return t(`chat.runStatus.${run.value.status}`)
  return t('chat.preparing')
})
const runFinished = computed(() => !!run.value && !active.value)
const errorText = computed(() => {
  const code = run.value?.error_code
  if (!code) return ''
  return te(`chat.errors.${code}`) ? t(`chat.errors.${code}`) : t('chat.retryHint')
})
const showStats = computed(() => active.value || runFinished.value)

async function openBranch(id: string) { await chat.selectTenant(tenant.value); await chat.openSession(id) }
async function send() { if (await chat.send(prompt.value)) prompt.value = '' }
async function respond() { if (await chat.respond(answer.value)) answer.value = '' }
/** Enter sends; Shift+Enter inserts a newline (IME composition is left alone). */
function onComposerKey(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void send()
}
</script>

<template>
  <main class="conversation-page">
    <header class="title-bar">
      <h1 class="title">{{ title }}</h1>
      <span class="status" role="status" aria-live="polite">{{ statusText }}</span>
      <el-button v-if="connection === 'reconnecting' || connection === 'closed'" size="small" @click="chat.reconnect">{{ t('chat.reconnect') }}</el-button>
      <el-button size="small" :disabled="submitting || loading" @click="chat.initialize(String(route.params.sessionId || ''))">{{ t('common.refresh') }}</el-button>
    </header>
    <p v-if="connection === 'reconnecting'" class="notice" role="status">{{ t('chat.reconnecting') }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="error" />
    <p v-if="errorText" class="notice notice--error" role="alert">{{ errorText }}</p>

    <el-skeleton v-if="loading" :rows="5" animated />
    <section v-else class="thread" :aria-busy="loading" :aria-label="t('chat.threadLabel')">
      <el-empty v-if="!sessionId && !timeline.length" :description="t('chat.emptyTitle')" />
      <p v-else-if="sessionId && !timeline.length" class="muted">{{ t('chat.emptyHint') }}</p>
      <ChatTimeline :items="timeline" :stats="stats" :show-stats="showStats" />
    </section>

    <div class="composer-wrap">
      <form v-if="pendingInput" class="composer input-request" @submit.prevent="respond">
        <div class="candidate-options"><el-button v-for="candidate in pendingInput.candidates || []" :key="candidate" :disabled="submitting" @click="answer = candidate">{{ candidate }}</el-button></div>
        <label for="answer">{{ t('chat.answerLabel') }}</label><p class="message-text">{{ pendingInput.question }}</p>
        <el-input id="answer" v-model="answer" type="textarea" :rows="3" :maxlength="100000" :disabled="submitting || cancelling" />
        <div class="composer-actions"><el-button type="primary" native-type="submit" :loading="submitting" :disabled="!answer.trim() || cancelling">{{ t('chat.submitAnswer') }}</el-button></div>
      </form>
      <form v-else class="composer" @submit.prevent="send">
        <label class="visually-hidden" for="prompt">{{ t('chat.yourMessage') }}</label>
        <el-input id="prompt" v-model="prompt" type="textarea" autosize :rows="2" :maxlength="100000" :disabled="submitting || active || loading" :placeholder="t('chat.placeholder')" @keydown="onComposerKey" />
        <div class="composer-toolbar">
          <el-select v-model="versionId" size="small" class="agent-select" :disabled="loading || submitting || !!sessionId" :placeholder="t('chat.selectAgent')" :aria-label="t('chat.newSessionAgent')">
            <el-option v-for="agent in agents" :key="agent.id" :label="agent.name" :value="agent.published_version_id!" />
          </el-select>
          <el-button size="small" disabled :title="t('common.soon')" :aria-label="t('common.soon')">@</el-button>
          <span class="toolbar-spacer" />
          <el-button v-if="active" size="small" :loading="cancelling" :disabled="cancelling" @click="chat.cancel">{{ t('chat.stop') }}</el-button>
          <el-button type="primary" size="small" native-type="submit" :loading="submitting" :disabled="!prompt.trim() || active || loading || (!sessionId && !versionId)">{{ t('chat.send') }}</el-button>
        </div>
      </form>

      <p v-if="!agents.length && !loading && tenant" class="muted">{{ t('chat.noAgents') }}</p>
      <p v-if="!sessions.length && !loading && tenant && !sessionId" class="muted">{{ t('chat.noSessionsInSpace') }}</p>

      <el-collapse v-if="tenant" v-model="tools" class="tools">
        <el-collapse-item name="tools" :title="t('chat.sessionTools')">
          <div class="tool-stack">
            <ModelBranchControls :tenant="tenant" :session="sessionId" :disabled="active || loading || submitting" @created="openBranch" />
            <MemorySnapshotControl v-if="sessionId" :tenant="tenant" :session="sessionId" :disabled="active || loading || submitting" />
          </div>
        </el-collapse-item>
      </el-collapse>
      <RuntimeControls v-if="tenant && run" :tenant="tenant" :run="run" @resume="chat.openSession(sessionId)" />
    </div>
  </main>
</template>

<style scoped>
.conversation-page { display: flex; flex-direction: column; gap: 12px; max-width: 880px; margin: 0 auto; min-height: calc(100vh - 48px); }
.title-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; min-height: 40px; }
.title { margin: 0; font-size: 16px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1 1 auto; }
.status { font-size: 13px; color: var(--muted-text); }
.thread { flex: 1; min-height: 240px; padding: 8px 0 16px; }
.composer-wrap { position: sticky; bottom: 0; display: grid; gap: 8px; padding-bottom: 8px; background: var(--color-bg-container); }
.composer { display: grid; gap: 8px; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: 14px; background: var(--color-bg-container); box-shadow: var(--shadow-1); }
.composer :deep(.el-textarea__inner) { box-shadow: none; border: 0; padding: 4px 2px; resize: none; }
.composer-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.agent-select { width: 220px; }
.toolbar-spacer { flex: 1; }
.composer-actions { display: flex; justify-content: flex-end; }
.input-request { border-color: var(--el-color-warning); }
.tools { border: 0; }
.tool-stack { display: grid; gap: 12px; }
.notice { margin: 0; font-size: 13px; color: var(--muted-text); }
.notice--error { color: var(--el-color-danger); }
.message-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; }
.muted { color: var(--muted-text); font-size: 14px; line-height: 1.6; }
.candidate-options { display: flex; flex-wrap: wrap; gap: 8px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (max-width: 760px) { .agent-select { width: 100%; } .bubble { max-width: 92%; } }
</style>
