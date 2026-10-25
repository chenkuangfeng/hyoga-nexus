<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ModelBranchControls from '../../components/ModelBranchControls.vue'
import RuntimeControls from '../../components/RuntimeControls.vue'
import { useConversation } from '../../composables/useConversation'
import { errorLabels, statusLabels } from '../../types/chat'
const chat = useConversation()
const { workspaces, agents, sessions, workspace, sessionId, versionId, timeline, run, pendingInput,
  error, loading, submitting, connection, cancelling, active } = chat
const prompt = ref(''), answer = ref('')
onMounted(chat.initialize)
async function openBranch(id: string) { await chat.selectWorkspace(workspace.value); await chat.openSession(id) }
async function send() { if (await chat.send(prompt.value)) prompt.value = '' }
async function respond() { if (await chat.respond(answer.value)) answer.value = '' }
</script>

<template>
  <main class="conversation-page">
    <header class="page-header">
      <div><p class="eyebrow">HYOGA NEXUS / 织枢</p><h1>对话工作台</h1></div>
      <el-button :disabled="submitting || loading" @click="chat.initialize">刷新会话</el-button>
    </header>
    <p class="intro">选择已发布的智能体，持续对话并查看工具执行进度。模型随智能体版本固定。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="error" />
    <div class="conversation-layout">
      <aside class="conversation-sidebar" aria-label="空间和会话">
        <label for="workspace-select">工作空间</label>
        <el-select id="workspace-select" :model-value="workspace" :disabled="loading || submitting" placeholder="选择空间" @change="chat.selectWorkspace">
          <el-option v-for="item in workspaces" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <label for="agent-select">新会话使用的智能体</label>
        <el-select id="agent-select" v-model="versionId" :disabled="loading || submitting" placeholder="选择已发布的 Native 智能体">
          <el-option v-for="agent in agents" :key="agent.id" :label="agent.name" :value="agent.published_version_id!" />
        </el-select>
        <el-button type="primary" :disabled="!versionId || loading" :loading="submitting" @click="chat.createSession">新建会话</el-button>
        <p v-if="workspace && !agents.length && !loading" class="muted">暂无已发布的 Native 智能体，请先完成智能体配置和发布。</p>
        <ModelBranchControls :workspace="workspace" :session="sessionId" :disabled="active || loading || submitting" @created="openBranch" />
        <h2>会话记录</h2>
        <nav class="session-list" aria-label="选择会话">
          <button v-for="item in sessions" :key="item.id" type="button" :aria-current="item.id === sessionId ? 'page' : undefined"
            :class="{ selected: item.id === sessionId }" :disabled="submitting" @click="chat.openSession(item.id)">
            {{ item.title || `会话 ${item.id.slice(-8)}` }}
          </button>
        </nav>
        <p v-if="!sessions.length && !loading" class="muted">暂无会话</p>
      </aside>
      <section class="chat-panel" aria-label="会话内容" :aria-busy="loading">
        <div class="run-status" role="status" aria-live="polite">
          <span>{{ cancelling ? '正在停止，请等待执行结果确认' : run ? statusLabels[run.status] : '准备开始对话' }}</span>
          <span v-if="connection === 'reconnecting'">连接中断，正在自动重连</span>
          <span v-if="run?.error_code" class="muted">{{ errorLabels[run.error_code] || '运行未完成，请检查配置后重试' }}</span>
        </div>
        <el-button v-if="connection === 'reconnecting' || connection === 'closed'" @click="chat.reconnect">重新连接</el-button>
        <el-skeleton v-if="loading" :rows="5" animated />
        <div v-else class="message-list">
          <el-empty v-if="!sessionId" description="选择或新建一个会话" />
          <p v-else-if="!timeline.length" class="muted">写下你的第一个问题。</p>
          <template v-for="item in timeline" :key="item.id">
            <article v-if="item.kind === 'message'" class="chat-message" :class="item.role">
              <h2>{{ item.role === 'user' ? '你' : '智能体' }}</h2>
              <div class="message-text">{{ item.content }}</div>
            </article>
            <details v-else class="tool-card">
              <summary>{{ item.name }} · {{ item.status }}</summary><pre v-if="item.summary">{{ item.summary }}</pre>
            </details>
          </template>
        </div>
        <form v-if="pendingInput" class="composer input-request" @submit.prevent="respond">
          <div class="candidate-options"><el-button v-for="candidate in pendingInput.candidates || []" :key="candidate" :disabled="submitting" @click="answer = candidate">{{ candidate }}</el-button></div>
          <label for="answer">智能体需要你的回答</label><p class="message-text">{{ pendingInput.question }}</p>
          <el-input id="answer" v-model="answer" type="textarea" :rows="3" :maxlength="100000" :disabled="submitting || cancelling" />
          <div class="composer-actions"><el-button type="primary" native-type="submit" :loading="submitting" :disabled="!answer.trim() || cancelling">提交回答</el-button></div>
        </form>
        <form v-else class="composer" @submit.prevent="send">
          <label for="prompt">你的消息</label>
          <el-input id="prompt" v-model="prompt" type="textarea" :rows="4" :maxlength="100000" :disabled="!sessionId || submitting || active || loading" placeholder="输入问题，点击发送" />
          <div class="composer-actions"><el-button type="primary" native-type="submit" :loading="submitting" :disabled="!sessionId || !prompt.trim() || active || loading">发送消息</el-button></div>
        </form>
        <RuntimeControls v-if="workspace && run" :workspace="workspace" :run="run" @resume="chat.openSession(sessionId)" />
        <el-button v-if="active" class="stop-button" :loading="cancelling" :disabled="cancelling" @click="chat.cancel">停止运行</el-button>
      </section>
    </div>
  </main>
</template>

<style scoped>
.conversation-page { max-width: 1440px; }
.conversation-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 24px; margin-top: 24px; align-items: start; }
.conversation-sidebar, .chat-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; min-width: 0; }
.conversation-sidebar { display: flex; flex-direction: column; gap: 12px; }
.conversation-sidebar h2 { margin-top: 20px; }
label { font-size: 14px; font-weight: 600; }
.session-list { display: flex; flex-direction: column; gap: 8px; max-height: 50vh; overflow-y: auto; }
.session-list button { font: inherit; min-height: 44px; text-align: left; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); padding: 10px 12px; cursor: pointer; overflow-wrap: anywhere; }
.session-list button:hover, .session-list button.selected { background: var(--selected); border-color: var(--el-color-primary); }
.run-status { display: flex; flex-wrap: wrap; gap: 12px; padding-bottom: 16px; border-bottom: 1px solid var(--border); font-weight: 600; }
.message-list { min-height: 240px; padding: 8px 0 24px; }
.chat-message { padding: 20px 0; }
.chat-message.user { padding: 16px; margin-top: 16px; background: var(--selected); border-radius: 8px; }
.chat-message h2 { font-size: 14px; margin-bottom: 10px; }
.message-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; }
.muted { color: var(--muted-text); font-size: 14px; line-height: 1.6; font-weight: 400; }
.tool-list { display: grid; gap: 10px; margin-top: 16px; }
.tool-card { padding: 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 14px; }
summary { cursor: pointer; min-height: 24px; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; line-height: 1.6; }
.composer { display: grid; gap: 12px; border-top: 1px solid var(--border); padding-top: 20px; }
.composer-actions { display: flex; justify-content: flex-end; }
.stop-button { margin-top: 12px; }
@media (max-width: 760px) { .conversation-layout { grid-template-columns: 1fr; gap: 16px; } .conversation-sidebar, .chat-panel { padding: 16px; } .session-list { max-height: 160px; } }
</style>
