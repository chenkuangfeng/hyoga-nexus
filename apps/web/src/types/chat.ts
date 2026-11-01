export type RunStatus = 'queued' | 'running' | 'waiting_input' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
export interface Tenant { id: string; name: string; via_organization: boolean }
export interface Agent { id: string; name: string; runtime_type: string; published_version_id: string | null }
/** `org_unit_id` is set when the owner came through an organization; it drives the "组织访问" tag. */
export interface Conversation { id: string; title: string; agent_version_id: string; updated_at: string; org_unit_id: string | null }
/** `queue_position` is the 1-based FIFO place returned when a submission is queued (null otherwise). */
export interface Run { id: string; status: RunStatus; error_code: string | null; queue_position: number | null }
export interface Message { id: string; run_id: string | null; sequence: number; role: string; content: string }
/** `received_at` (ms) is set by this page when the event arrives; it is not part of the server payload. */
export interface RunEvent { event_id: string; run_id: string; sequence: number; event_type: string; payload: Record<string, unknown>; received_at?: number }
export interface History { messages: Message[]; latest_run: Run | null }
export interface InputRequest { input_request_id: string; question: string; candidates?: string[] }
export const terminal = (status: RunStatus) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
