/**
 * 把平台 Run 事件转换为 WeKnora 智能体时间线（AgentStreamDisplay）使用的事件流。
 *
 * AgentStreamDisplay 只认识 WeKnora 的 `agentEventStream` 事件格式（answer / tool_call / stop），
 * 本模块负责映射，使组件本身可以原样复用，不必为 Nexus 另写一套渲染。
 *
 * 映射规则：
 * - `message.delta`：同一轮（turn）的文本合并为一个 `answer` 事件；遇到工具事件、轮次变化或运行结束时该 answer 标记为 done。
 * - `tool.started` / `tool.completed` / `tool.failed`：按 invocation_id 对应为一个 `tool_call`，pending / success 随之更新。
 * - `approval.requested` / `approval.resolved`：映射为 WeKnora 的 `tool_approval_required`，由 `ToolApprovalCard` 渲染。
 *   事件不携带工具参数（只对 Run 所有者通过审批接口开放），参数由调用方经 `approvalArgs` 传入。
 * - `input.requested` / `input.received`：映射为 `agent_prompt_required`（kind = ask_user），由 `AskUserCard` 渲染；
 *   候选项作为选项，并允许自由输入。
 * - `memory.draft_proposed`：模型在对话中提出的记忆草稿，映射为 `memory_draft`，由 `MemoryDraftCard` 渲染，
 *   所有者可在对话内发布或拒绝（openspec 2026-11-06-memory-evolution E1）。
 * - `memory.used` 不进入时间线，由 `usedMemoriesFromEvents` 汇总为 WeKnora 的“本次使用了 N 条记忆”行（B5）。
 * - 运行被取消时追加 `stop`，与 WeKnora 的用户停止事件一致。
 * - 运行失败或中断时，与 WeKnora 处理运行级 error 一致：把错误说明作为一段已完成的回答追加（需传入 `failureMessage`）。
 * - 其他事件（进度、模型调用等）不进入时间线。
 *
 * 纯函数，不依赖 Vue 或网络，便于单元测试。
 */
import { TERMINAL_RUN_STATUSES, type RunEvent } from '../api/native-run-types'

/** AgentStreamDisplay 消费的事件（只列出本模块会生成的字段）。 */
export interface AgentStreamAnswer {
  type: 'answer'
  id: string
  turn: number
  content: string
  done: boolean
}

export interface AgentStreamToolCall {
  type: 'tool_call'
  tool_call_id: string
  tool_name: string
  pending: boolean
  success?: boolean
  tool_data: { summary?: string; error_code?: string }
}

export interface AgentStreamStop {
  type: 'stop'
}

/** WeKnora `tool_approval_required`; `pending_id` is the Nexus approval id. */
export interface AgentStreamApproval {
  type: 'tool_approval_required'
  pending_id: string
  mcp_tool_name: string
  service_name: string
  args_json: string
  resolved: boolean
  approved?: boolean
  canceled?: boolean
}

/** WeKnora `agent_prompt_required` (ask_user); `pending_id` is the Nexus input request id. */
export interface AgentStreamPrompt {
  type: 'agent_prompt_required'
  kind: 'ask_user'
  pending_id: string
  request: { question: string; options?: string[]; allow_free_text: boolean }
  resolved: boolean
  answered?: boolean
  canceled?: boolean
}

/** A memory draft the model proposed in this Run; the owner reviews it in the conversation. */
export interface AgentStreamMemoryDraft {
  type: 'memory_draft'
  draft_id: string
  kind: string
  diff: string
  topic: string
  /** Entry the draft edits, or null for a new entry. */
  base_entry: { id: string; title: string; version: number } | null
  /** Titles of entries the draft may conflict with (review hint only). */
  conflicts: string[]
}

export type AgentStreamEvent = AgentStreamAnswer | AgentStreamToolCall | AgentStreamStop | AgentStreamApproval
  | AgentStreamPrompt | AgentStreamMemoryDraft

/** One memory the turn used, in the shape of WeKnora's `used_memories` (content shows the entry title). */
export interface UsedMemoryRef {
  id: string
  kind: string
  content: string
}

/** Memories a Run injected or read (`memory.used`), de-duplicated by entry id in first-use order. */
export function usedMemoriesFromEvents(events: readonly RunEvent[]): UsedMemoryRef[] {
  const seen = new Map<string, UsedMemoryRef>()
  for (const event of events) {
    if (event.event_type !== 'memory.used' || !Array.isArray(event.payload.entries)) continue
    for (const entry of event.payload.entries) {
      if (!entry || typeof entry !== 'object') continue
      const { id, kind, title } = entry as Record<string, unknown>
      if (typeof id !== 'string' || seen.has(id)) continue
      seen.set(id, { id, kind: typeof kind === 'string' ? kind : 'memory', content: typeof title === 'string' ? title : '' })
    }
  }
  return [...seen.values()]
}

export interface AgentEventStreamOptions {
  /** Arguments of pending approvals by approval id, from `GET .../approvals`. */
  approvalArgs?: ReadonlyMap<string, Record<string, unknown>>
  /** Text shown as the answer of a failed or interrupted Run, from its error code (may be empty). */
  failureMessage?: (errorCode: string) => string
}

/** 运行结束时的状态；只有 cancelled 会追加 stop 事件。 */
export function toAgentEventStream(events: readonly RunEvent[], runStatus: string | null,
  options: AgentEventStreamOptions = {}): AgentStreamEvent[] {
  const stream: AgentStreamEvent[] = []
  const toolById = new Map<string, AgentStreamToolCall>()
  const approvalById = new Map<string, AgentStreamApproval>()
  const promptById = new Map<string, AgentStreamPrompt>()
  let openAnswer: AgentStreamAnswer | null = null

  const closeAnswer = () => {
    if (openAnswer) openAnswer.done = true
    openAnswer = null
  }

  for (const event of events) {
    const payload = event.payload
    switch (event.event_type) {
      case 'message.delta': {
        const text = typeof payload.text === 'string' ? payload.text : ''
        const turn = typeof payload.turn === 'number' ? payload.turn : 0
        if (openAnswer && openAnswer.turn === turn) {
          openAnswer.content += text
        } else {
          closeAnswer()
          openAnswer = { type: 'answer', id: `answer-${event.run_id}-${turn}-${event.sequence}`, turn, content: text, done: false }
          stream.push(openAnswer)
        }
        break
      }
      case 'tool.started': {
        closeAnswer()
        const id = typeof payload.invocation_id === 'string' ? payload.invocation_id : ''
        if (!id || toolById.has(id)) break
        const call: AgentStreamToolCall = {
          type: 'tool_call',
          tool_call_id: id,
          tool_name: typeof payload.name === 'string' ? payload.name : 'tool',
          pending: true,
          tool_data: {},
        }
        toolById.set(id, call)
        stream.push(call)
        break
      }
      case 'tool.completed':
      case 'tool.failed': {
        closeAnswer()
        const id = typeof payload.invocation_id === 'string' ? payload.invocation_id : ''
        const call = toolById.get(id)
        if (!call) break
        call.pending = false
        call.success = event.event_type === 'tool.completed'
        call.tool_data = {
          summary: typeof payload.summary === 'string' ? payload.summary : undefined,
          error_code: typeof payload.error_code === 'string' ? payload.error_code : undefined,
        }
        break
      }
      case 'approval.requested': {
        closeAnswer()
        const id = typeof payload.approval_id === 'string' ? payload.approval_id : ''
        if (!id || approvalById.has(id)) break
        const args = options.approvalArgs?.get(id)
        const card: AgentStreamApproval = {
          type: 'tool_approval_required',
          pending_id: id,
          mcp_tool_name: typeof payload.tool_name === 'string' ? payload.tool_name : 'tool',
          service_name: '',
          args_json: args ? JSON.stringify(args, null, 2) : '',
          resolved: false,
        }
        approvalById.set(id, card)
        stream.push(card)
        break
      }
      case 'approval.resolved': {
        const card = approvalById.get(typeof payload.approval_id === 'string' ? payload.approval_id : '')
        if (!card) break
        card.resolved = true
        card.approved = payload.approved === true
        break
      }
      case 'input.requested': {
        closeAnswer()
        const id = typeof payload.input_request_id === 'string' ? payload.input_request_id : ''
        if (!id || promptById.has(id)) break
        const candidates = Array.isArray(payload.candidates)
          ? payload.candidates.filter((item): item is string => typeof item === 'string') : []
        const card: AgentStreamPrompt = {
          type: 'agent_prompt_required',
          kind: 'ask_user',
          pending_id: id,
          request: {
            question: typeof payload.question === 'string' ? payload.question : '',
            ...(candidates.length ? { options: candidates } : {}),
            allow_free_text: true,
          },
          resolved: false,
        }
        promptById.set(id, card)
        stream.push(card)
        break
      }
      case 'memory.draft_proposed': {
        closeAnswer()
        const id = typeof payload.draft_id === 'string' ? payload.draft_id : ''
        if (!id) break
        const base = payload.base_entry
        const baseEntry = base && typeof base === 'object' && typeof (base as Record<string, unknown>).id === 'string'
          ? {
              id: (base as Record<string, unknown>).id as string,
              title: String((base as Record<string, unknown>).title ?? ''),
              version: Number((base as Record<string, unknown>).version ?? 0),
            }
          : null
        const hints = payload.annotations && typeof payload.annotations === 'object'
          ? (payload.annotations as Record<string, unknown>).conflict : undefined
        stream.push({
          type: 'memory_draft',
          draft_id: id,
          kind: typeof payload.kind === 'string' ? payload.kind : 'memory',
          diff: typeof payload.diff === 'string' ? payload.diff : '',
          topic: typeof payload.topic === 'string' ? payload.topic : '',
          base_entry: baseEntry,
          conflicts: Array.isArray(hints)
            ? hints.map(hint => (hint && typeof hint === 'object' ? String((hint as Record<string, unknown>).title ?? '') : ''))
              .filter(Boolean)
            : [],
        })
        break
      }
      case 'input.received': {
        const card = promptById.get(typeof payload.input_request_id === 'string' ? payload.input_request_id : '')
        if (!card) break
        card.resolved = true
        card.answered = true
        break
      }
      default:
        break
    }
  }

  // A Run that ended while a card was still open closes it, so history never shows an answerable card.
  if (runStatus !== null && TERMINAL_RUN_STATUSES.has(runStatus)) {
    for (const card of [...approvalById.values(), ...promptById.values()]) {
      if (!card.resolved) { card.resolved = true; card.canceled = true }
    }
  }

  // 运行未结束时最后一段文本仍在流式输出，不能标记为 done。
  if (runStatus !== null && TERMINAL_RUN_STATUSES.has(runStatus)) closeAnswer()
  if (runStatus === 'cancelled') stream.push({ type: 'stop' })
  if ((runStatus === 'failed' || runStatus === 'interrupted') && options.failureMessage) {
    const terminal = [...events].reverse().find(e => e.event_type === `run.${runStatus}`)
    const code = typeof terminal?.payload.error_code === 'string' ? terminal.payload.error_code : ''
    const runId = terminal?.run_id ?? events[events.length - 1]?.run_id ?? 'run'
    stream.push({ type: 'answer', id: `answer-${runId}-failure`, turn: -1, content: options.failureMessage(code), done: true })
  }
  return stream
}
