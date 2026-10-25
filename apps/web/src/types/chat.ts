export type RunStatus = 'queued' | 'running' | 'waiting_input' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
export interface Workspace { id: string; name: string }
export interface Agent { id: string; name: string; runtime_type: string; published_version_id: string | null }
export interface Conversation { id: string; title: string; agent_version_id: string }
export interface Run { id: string; status: RunStatus; error_code: string | null }
export interface Message { id: string; run_id: string | null; sequence: number; role: string; content: string }
export interface RunEvent { event_id: string; run_id: string; sequence: number; event_type: string; payload: Record<string, unknown> }
export interface History { messages: Message[]; latest_run: Run | null }
export interface InputRequest { input_request_id: string; question: string; candidates?: string[] }
export const terminal = (status: RunStatus) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
export const statusLabels: Record<RunStatus, string> = {
  queued: '排队中', running: '正在生成', waiting_input: '等待你的回答', waiting_approval: '等待审核',
  completed: '已完成', failed: '运行失败', cancelled: '已取消', interrupted: '已中断，部分操作结果未知',
}

export const errorLabels: Record<string, string> = {
  runtime_not_configured: '智能体或模型尚未配置，请联系管理员',
  runtime_capability_unavailable: '智能体绑定了尚未接入的能力，请调整配置',
  model_credential_unavailable: '模型凭据不可用，请联系管理员',
  model_timeout: '模型响应超时，请稍后重试',
  model_provider_unavailable: '模型服务暂时不可用',
  model_rate_limited: '模型请求达到限额，请稍后重试',
  model_context_exceeded: '会话内容超过模型限制，请新建会话',
  model_stream_invalid: '模型响应不完整，请重试',
  budget_exhausted: '本次运行已达到执行预算',
  run_authorization_denied: '访问权限已发生变化，请检查授权',
  worker_lease_expired: '执行连接中断，部分操作结果需要核实',
  interrupted: '部分操作结果未知，请核实后继续',
  runtime_budget_invalid: '执行预算配置无效，请联系管理员',
}
