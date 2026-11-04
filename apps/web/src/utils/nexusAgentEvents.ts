/**
 * 把平台 Run 事件转换为 WeKnora 智能体时间线（AgentStreamDisplay）使用的事件流。
 *
 * AgentStreamDisplay 只认识 WeKnora 的 `agentEventStream` 事件格式（answer / tool_call / stop），
 * 本模块负责映射，使组件本身可以原样复用，不必为 Nexus 另写一套渲染。
 *
 * 映射规则：
 * - `message.delta`：同一轮（turn）的文本合并为一个 `answer` 事件；遇到工具事件、轮次变化或运行结束时该 answer 标记为 done。
 * - `tool.started` / `tool.completed` / `tool.failed`：按 invocation_id 对应为一个 `tool_call`，pending / success 随之更新。
 * - 运行被取消时追加 `stop`，与 WeKnora 的用户停止事件一致。
 * - 其他事件（进度、等待输入、审批等）不进入时间线；它们由页面的告警条与输入卡片处理。
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

export type AgentStreamEvent = AgentStreamAnswer | AgentStreamToolCall | AgentStreamStop

/** 运行结束时的状态；只有 cancelled 会追加 stop 事件。 */
export function toAgentEventStream(events: readonly RunEvent[], runStatus: string | null): AgentStreamEvent[] {
  const stream: AgentStreamEvent[] = []
  const toolById = new Map<string, AgentStreamToolCall>()
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
      default:
        break
    }
  }

  // 运行未结束时最后一段文本仍在流式输出，不能标记为 done。
  if (runStatus !== null && TERMINAL_RUN_STATUSES.has(runStatus)) closeAnswer()
  if (runStatus === 'cancelled') stream.push({ type: 'stop' })
  return stream
}
