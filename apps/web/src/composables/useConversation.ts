import { computed, onBeforeUnmount, ref } from 'vue'
import { api, parseEvent, runPath } from '../api/chat'
import type { Agent, Conversation, InputRequest, Message, Run, RunEvent, Workspace } from '../types/chat'
import { terminal } from '../types/chat'

export function useConversation() {
  const workspaces = ref<Workspace[]>([]), agents = ref<Agent[]>([]), sessions = ref<Conversation[]>([])
  const workspace = ref(''), sessionId = ref(''), versionId = ref('')
  const messages = ref<Message[]>([]), run = ref<Run | null>(null), events = ref<RunEvent[]>([])
  const pendingInput = ref<InputRequest | null>(null), error = ref(''), loading = ref(false), submitting = ref(false)
  const connection = ref<'idle' | 'connected' | 'reconnecting' | 'closed'>('idle'), cancelling = ref(false)
  let source: EventSource | undefined, controller: AbortController | undefined, generation = 0
  let sendAttempt: { text: string; key: string; session: string } | undefined
  let responseAttempt: { text: string; key: string; request: string } | undefined
  const active = computed(() => !!run.value && !terminal(run.value.status))
  const availableAgents = computed(() => agents.value.filter(agent => agent.runtime_type === 'native' && agent.published_version_id))
  const visibleMessages = computed(() => messages.value.filter(message => message.role === 'user' || (message.role === 'assistant' && message.run_id !== run.value?.id)))
  const streamed = computed(() => {
    const byTurn = new Map<number, string>()
    for (const event of events.value) if (event.event_type === 'message.delta' && typeof event.payload.text === 'string' && typeof event.payload.turn === 'number') {
      byTurn.set(event.payload.turn, (byTurn.get(event.payload.turn) || '') + event.payload.text)
    }
    return Array.from(byTurn, ([turn, text]) => ({ turn, text }))
  })
  const tools = computed(() => {
    const byId = new Map<string, { id: string; name: string; status: string; summary: string }>()
    for (const event of events.value) {
      const id = event.payload.invocation_id
      if (typeof id !== 'string') continue
      if (event.event_type === 'tool.started') byId.set(id, { id, name: String(event.payload.name || '工具'), status: '运行中', summary: '' })
      else if (['tool.completed', 'tool.failed'].includes(event.event_type)) {
        const item = byId.get(id)
        if (item) { item.status = event.event_type === 'tool.completed' ? '已完成' : String(event.payload.status || '失败'); item.summary = String(event.payload.summary || '') }
      }
    }
    return [...byId.values()]
  })
  function resetConnection() { source?.close(); source = undefined; connection.value = 'idle' }
  function attach(cursor = 0) {
    resetConnection()
    const current = run.value
    if (!current) return
    const epoch = generation, id = current.id
    const stream = new EventSource(`/api/v1${runPath(workspace.value, id)}/events?after_sequence=${cursor}`)
    source = stream
    let last = cursor
    stream.onopen = () => { if (epoch === generation) connection.value = 'connected' }
    stream.addEventListener('stream.closed', () => { stream.close(); connection.value = 'closed'; error.value = '事件连接已关闭，请刷新检查访问权限。' })
    stream.addEventListener('run.event', event => {
      if (epoch !== generation || run.value?.id !== id) return
      try {
        const item = parseEvent(JSON.parse((event as MessageEvent<string>).data))
        if (item.run_id !== id || item.sequence <= last) return
        if (item.sequence !== last + 1) { stream.close(); attach(last); return }
        last = item.sequence
        events.value.push(item)
        if (item.event_type === 'input.requested' && typeof item.payload.input_request_id === 'string' && typeof item.payload.question === 'string') {
          pendingInput.value = { input_request_id: item.payload.input_request_id, question: item.payload.question }
        }
        if (item.event_type === 'input.received') pendingInput.value = null
        if (item.event_type === 'run.started') run.value.status = 'running'
        if (item.event_type === 'run.cancel_requested') cancelling.value = !terminal(run.value.status)
        const statuses = ['completed', 'failed', 'cancelled', 'interrupted', 'waiting_input', 'waiting_approval'] as const
        for (const status of statuses) if (item.event_type === `run.${status}`) {
          run.value.status = status
          run.value.error_code = typeof item.payload.error_code === 'string' ? item.payload.error_code : null
          cancelling.value = false
          // Replaying a historical wait must not close a stream whose Run has already resumed.
          if (terminal(status)) { stream.close(); connection.value = 'idle' }
        }
      } catch { stream.close(); connection.value = 'closed'; error.value = '无法读取运行事件，请重连。' }
    })
    stream.onerror = () => {
      if (epoch !== generation) return
      if (run.value?.status === 'waiting_input' && pendingInput.value) { stream.close(); connection.value = 'idle' }
      else connection.value = 'reconnecting'
    }
  }
  async function initialize() {
    loading.value = true; error.value = ''
    try { workspaces.value = await api.workspaces(); if (workspaces.value[0]) await selectWorkspace(workspaces.value[0].id) }
    catch (cause) { error.value = String(cause instanceof Error ? cause.message : cause) }
    finally { loading.value = false }
  }
  async function selectWorkspace(id: string) {
    const epoch = ++generation
    controller?.abort(); controller = new AbortController(); resetConnection()
    workspace.value = id; sessionId.value = ''; run.value = null; messages.value = []; events.value = []; sessions.value = []; agents.value = []; pendingInput.value = null; cancelling.value = false
    error.value = ''; loading.value = true
    try {
      const [agentRows, sessionRows] = await Promise.all([api.agents(id, controller.signal), api.sessions(id, controller.signal)])
      if (epoch !== generation) return
      agents.value = agentRows; sessions.value = sessionRows
      versionId.value = availableAgents.value[0]?.published_version_id || ''
      if (sessionRows[0]) await openSession(sessionRows[0].id)
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '无法加载空间' }
    finally { if (epoch === generation || workspace.value === id) loading.value = false }
  }
  async function openSession(id: string) {
    const epoch = ++generation
    controller?.abort(); controller = new AbortController(); resetConnection()
    sessionId.value = id; messages.value = []; events.value = []; run.value = null; pendingInput.value = null; cancelling.value = false; error.value = ''; loading.value = true
    try {
      let cursor = 0
      while (true) {
        const history = await api.history(workspace.value, id, cursor, controller.signal)
        if (epoch !== generation) return
        messages.value.push(...history.messages); run.value = history.latest_run
        if (history.messages.length < 200) break
        cursor = history.messages[history.messages.length - 1]!.sequence
      }
      attach()
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '无法加载会话' }
    finally { if (epoch === generation) loading.value = false }
  }
  async function createSession() {
    if (!versionId.value || submitting.value) return
    submitting.value = true; error.value = ''
    const epoch = generation
    try {
      const created = await api.createSession(workspace.value, versionId.value)
      if (epoch !== generation) return
      sessions.value.unshift(created); await openSession(created.id)
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '创建失败' }
    finally { submitting.value = false }
  }
  async function send(text: string): Promise<boolean> {
    if (!sessionId.value || active.value || submitting.value || !text.trim()) return false
    submitting.value = true; error.value = ''
    const epoch = generation
    if (sendAttempt?.text !== text || sendAttempt.session !== sessionId.value) sendAttempt = { text, key: crypto.randomUUID(), session: sessionId.value }
    try {
      await api.send(workspace.value, sessionId.value, text, sendAttempt.key)
      sendAttempt = undefined
      if (epoch !== generation) return false
      await openSession(sessionId.value); return true
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '发送失败'; return false }
    finally { submitting.value = false }
  }
  async function cancel() {
    if (!run.value || cancelling.value) return
    const epoch = generation
    cancelling.value = true; error.value = ''
    try { const result = await api.cancel(workspace.value, run.value.id); if (epoch === generation) { run.value = result; if (terminal(result.status)) cancelling.value = false } }
    catch (cause) { if (epoch === generation) { cancelling.value = false; error.value = cause instanceof Error ? cause.message : '停止失败' } }
  }
  async function respond(text: string): Promise<boolean> {
    if (!pendingInput.value || !run.value || submitting.value || !text.trim()) return false
    const epoch = generation, request = pendingInput.value.input_request_id
    submitting.value = true; error.value = ''
    if (responseAttempt?.text !== text || responseAttempt.request !== request) responseAttempt = { text, key: crypto.randomUUID(), request }
    try {
      await api.respond(workspace.value, run.value.id, request, text, responseAttempt.key)
      responseAttempt = undefined
      if (epoch !== generation) return false
      pendingInput.value = null; await openSession(sessionId.value); return true
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '回答提交失败'; return false }
    finally { submitting.value = false }
  }
  onBeforeUnmount(() => { generation++; controller?.abort(); resetConnection() })
  return { workspaces, agents: availableAgents, sessions, workspace, sessionId, versionId, messages: visibleMessages,
    run, pendingInput, error, loading, submitting, connection, cancelling, active, streamed, tools,
    initialize, selectWorkspace, openSession, createSession, send, cancel, respond, reconnect: () => attach(events.value.at(-1)?.sequence || 0) }
}
