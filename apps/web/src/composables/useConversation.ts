import { computed, onBeforeUnmount, ref } from 'vue'
import { api, parseEvent, runPath } from '../api/chat'
import { loadTenants, workspace } from '../stores/workspace'
import type { Agent, Conversation, InputRequest, Message, Run, RunEvent, Tenant } from '../types/chat'
import { terminal } from '../types/chat'

export function useConversation() {
  // Spaces come from the shell's shared store, so the sidebar selector and this page agree.
  const tenants = computed(() => workspace.tenants)
  const agents = ref<Agent[]>([]), sessions = ref<Conversation[]>([])
  const tenant = ref(''), sessionId = ref(''), versionId = ref('')
  const messages = ref<Message[]>([]), run = ref<Run | null>(null), events = ref<RunEvent[]>([])
  const pendingInput = ref<InputRequest | null>(null), error = ref(''), loading = ref(false), submitting = ref(false)
  const connection = ref<'idle' | 'connected' | 'reconnecting' | 'closed'>('idle'), cancelling = ref(false)
  let source: EventSource | undefined, controller: AbortController | undefined, generation = 0
  let sendAttempt: { text: string; key: string; session: string } | undefined
  let responseAttempt: { text: string; key: string; request: string } | undefined
  const active = computed(() => !!run.value && !terminal(run.value.status))
  // Position from the most recent 202 response only. It is a snapshot: the server does not push
  // position changes, so it is not replayed from the event stream after a reload.
  const queued = ref<{ run: string; position: number } | null>(null)
  const queueLabel = computed(() => {
    const current = run.value, position = queued.value
    if (!current || current.status !== 'queued' || !position || position.run !== current.id) return ''
    return position.position === 1 ? '排队中，即将开始' : `排队中，前方还有 ${position.position - 1} 个请求`
  })
  const availableAgents = computed(() => agents.value.filter(agent => agent.runtime_type === 'native' && agent.published_version_id))
  type TimelineItem = { kind: 'message'; id: string; role: string; content: string } |
    { kind: 'tool'; id: string; name: string; status: string; summary: string }
  const timeline = computed(() => {
    const result: TimelineItem[] = messages.value.filter(message => message.run_id !== run.value?.id && ['user', 'assistant'].includes(message.role))
      .map(message => ({ kind: 'message', id: message.id, role: message.role, content: message.content }))
    const users = messages.value.filter(message => message.run_id === run.value?.id && message.role === 'user')
    let userIndex = 0
    const appendUser = () => { const user = users[userIndex++]; if (user) result.push({ kind: 'message', id: user.id, role: user.role, content: user.content }) }
    appendUser()
    const turns = new Map<number, Extract<TimelineItem, { kind: 'message' }>>()
    const toolItems = new Map<string, Extract<TimelineItem, { kind: 'tool' }>>()
    for (const event of events.value) {
      if (event.event_type === 'message.delta' && typeof event.payload.text === 'string' && typeof event.payload.turn === 'number') {
        let item = turns.get(event.payload.turn)
        if (!item) { item = { kind: 'message', id: `turn-${event.payload.turn}`, role: 'assistant', content: '' }; turns.set(event.payload.turn, item); result.push(item) }
        item.content += event.payload.text
      }
      if (event.event_type === 'input.received') appendUser()
      const id = event.payload.invocation_id
      if (typeof id !== 'string') continue
      if (event.event_type === 'tool.started') {
        const item = { kind: 'tool' as const, id, name: String(event.payload.name || '工具'), status: '运行中', summary: '' }
        toolItems.set(id, item); result.push(item)
      } else if (['tool.completed', 'tool.failed'].includes(event.event_type)) {
        const item = toolItems.get(id)
        if (item) { item.status = event.event_type === 'tool.completed' ? '已完成' : event.payload.status === 'interrupted' ? '结果未知' : event.payload.status === 'cancelled' ? '已取消' : '执行失败'; item.summary = String(event.payload.summary || '') }
      }
    }
    return result
  })
  function resetConnection() { source?.close(); source = undefined; connection.value = 'idle' }
  function attach(cursor = 0) {
    resetConnection()
    const current = run.value
    if (!current) return
    const epoch = generation, id = current.id
    const stream = new EventSource(`/api/v1${runPath(tenant.value, id)}/events?after_sequence=${cursor}`)
    source = stream
    let last = cursor
    stream.onopen = () => { if (source === stream && epoch === generation) connection.value = 'connected' }
    stream.addEventListener('stream.closed', () => { if (source !== stream) return; stream.close(); connection.value = 'closed'; error.value = '事件连接已关闭，请刷新检查访问权限。' })
    stream.addEventListener('run.event', event => {
      if (source !== stream || epoch !== generation || run.value?.id !== id) return
      try {
        const item = parseEvent(JSON.parse((event as MessageEvent<string>).data))
        if (item.run_id !== id || item.sequence <= last) return
        if (item.sequence !== last + 1) { stream.close(); attach(last); return }
        last = item.sequence
        events.value.push(item)
        if (item.event_type === 'input.requested' && typeof item.payload.input_request_id === 'string' && typeof item.payload.question === 'string') {
          pendingInput.value = { input_request_id: item.payload.input_request_id, question: item.payload.question, candidates: Array.isArray(item.payload.candidates) ? item.payload.candidates.filter((value): value is string => typeof value === 'string') : [] }
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
          if (terminal(status)) { pendingInput.value = null; stream.close(); connection.value = 'idle' }
        }
      } catch { stream.close(); connection.value = 'closed'; error.value = '无法读取运行事件，请重连。' }
    })
    stream.onerror = () => {
      if (source !== stream || epoch !== generation) return
      if (run.value?.status === 'waiting_input' && pendingInput.value) { stream.close(); connection.value = 'idle' }
      else connection.value = 'reconnecting'
    }
  }
  async function initialize(preferred = '') {
    const epoch = ++generation
    controller?.abort(); controller = new AbortController(); resetConnection()
    tenant.value = ''; sessionId.value = ''; run.value = null; messages.value = []; events.value = []
    agents.value = []; sessions.value = []; pendingInput.value = null; cancelling.value = false
    loading.value = true; error.value = ''
    try {
      // Refresh the space list so a manual refresh also reports access errors for the spaces.
      await loadTenants()
      const id = workspace.tenantId || workspace.tenants[0]?.id || ''
      if (epoch !== generation) return
      if (id) await selectTenant(id, preferred)
    }
    catch (cause) { error.value = String(cause instanceof Error ? cause.message : cause) }
    finally { loading.value = false }
  }
  /** Load a space's agents and sessions. `preferred` (from the URL) is opened if it belongs to the space. */
  async function selectTenant(id: string, preferred = '') {
    const epoch = ++generation
    controller?.abort(); controller = new AbortController(); resetConnection()
    tenant.value = id; sessionId.value = ''; run.value = null; messages.value = []; events.value = []; sessions.value = []; agents.value = []; pendingInput.value = null; cancelling.value = false
    error.value = ''; loading.value = true
    try {
      const [agentRows, sessionRows] = await Promise.all([api.agents(id, controller.signal), api.sessions(id, controller.signal)])
      if (epoch !== generation) return
      agents.value = agentRows; sessions.value = sessionRows
      versionId.value = availableAgents.value[0]?.published_version_id || ''
      const target = sessionRows.find(row => row.id === preferred) || sessionRows[0]
      if (target) await openSession(target.id)
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '无法加载空间' }
    finally { if (epoch === generation || tenant.value === id) loading.value = false }
  }
  async function openSession(id: string) {
    const epoch = ++generation
    controller?.abort(); controller = new AbortController(); resetConnection()
    sessionId.value = id; messages.value = []; events.value = []; run.value = null; pendingInput.value = null; cancelling.value = false; error.value = ''; loading.value = true
    try {
      let cursor = 0
      while (true) {
        const history = await api.history(tenant.value, id, cursor, controller.signal)
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
      const created = await api.createSession(tenant.value, versionId.value)
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
      const accepted = await api.send(tenant.value, sessionId.value, text, sendAttempt.key)
      sendAttempt = undefined
      queued.value = accepted.queue_position === null ? null : { run: accepted.id, position: accepted.queue_position }
      if (epoch !== generation) return false
      await openSession(sessionId.value); return true
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '发送失败'; return false }
    finally { submitting.value = false }
  }
  async function cancel() {
    if (!run.value || cancelling.value) return
    const epoch = generation
    cancelling.value = true; error.value = ''
    try { const result = await api.cancel(tenant.value, run.value.id); if (epoch === generation) { run.value = result; if (terminal(result.status)) { pendingInput.value = null; cancelling.value = false; resetConnection() } } }
    catch (cause) { if (epoch === generation) { cancelling.value = false; error.value = cause instanceof Error ? cause.message : '停止失败' } }
  }
  async function respond(text: string): Promise<boolean> {
    if (!pendingInput.value || !run.value || submitting.value || !text.trim()) return false
    const epoch = generation, request = pendingInput.value.input_request_id
    submitting.value = true; error.value = ''
    if (responseAttempt?.text !== text || responseAttempt.request !== request) responseAttempt = { text, key: crypto.randomUUID(), request }
    try {
      await api.respond(tenant.value, run.value.id, request, text, responseAttempt.key)
      responseAttempt = undefined
      if (epoch !== generation) return false
      pendingInput.value = null; await openSession(sessionId.value); return true
    } catch (cause) { if (epoch === generation) error.value = cause instanceof Error ? cause.message : '回答提交失败'; return false }
    finally { submitting.value = false }
  }
  onBeforeUnmount(() => { generation++; controller?.abort(); resetConnection() })
  return { tenants, agents: availableAgents, sessions, tenant, sessionId, versionId, timeline, queueLabel,
    run, pendingInput, error, loading, submitting, connection, cancelling, active,
    initialize, selectTenant, openSession, createSession, send, cancel, respond, reconnect: () => attach(events.value.at(-1)?.sequence || 0) }
}
