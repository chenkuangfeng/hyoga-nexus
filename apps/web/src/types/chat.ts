export type RunStatus = 'queued' | 'running' | 'waiting_input' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
export interface Workspace { id: string; name: string }
export interface Agent { id: string; name: string; runtime_type: string; published_version_id: string | null }
export interface Conversation { id: string; title: string; agent_version_id: string }
export interface Run { id: string; status: RunStatus; error_code: string | null }
export interface Message { id: string; run_id: string | null; sequence: number; role: string; content: string }
export interface RunEvent { event_id: string; run_id: string; sequence: number; event_type: string; payload: Record<string, unknown> }
export interface History { messages: Message[]; latest_run: Run | null }
export interface InputRequest { input_request_id: string; question: string }
export const terminal = (status: RunStatus) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
export const statusLabels: Record<RunStatus, string> = {
  queued: '排队中', running: '正在生成', waiting_input: '等待你的回答', waiting_approval: '等待审核',
  completed: '已完成', failed: '运行失败', cancelled: '已取消', interrupted: '已中断，部分操作结果未知',
}
