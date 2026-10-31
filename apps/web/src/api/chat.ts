import type { Agent, Conversation, History, InputRequest, Message, Run, RunEvent, RunStatus, Tenant } from '../types/chat'

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('服务返回的数据格式无效')
  return value as Record<string, unknown>
}
function string(value: unknown): string {
  if (typeof value !== 'string') throw new Error('服务返回的数据格式无效')
  return value
}
function integer(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('事件序号无效')
  return value
}
function nullable(value: unknown) { return value === null ? null : string(value) }
function array<T>(value: unknown, parse: (value: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error('服务返回的数据格式无效')
  return value.map(parse)
}
export function parseRun(value: unknown): Run {
  const row = record(value), status = string(row.status)
  if (!['queued', 'running', 'waiting_input', 'waiting_approval', 'completed', 'failed', 'cancelled', 'interrupted'].includes(status)) throw new Error('未知运行状态')
  return { id: string(row.id), status: status as RunStatus, error_code: nullable(row.error_code) }
}
export function parseEvent(value: unknown): RunEvent {
  const row = record(value)
  return { event_id: string(row.event_id), run_id: string(row.run_id), sequence: integer(row.sequence),
    event_type: string(row.event_type), payload: record(row.payload) }
}
function parseSession(value: unknown): Conversation {
  const row = record(value)
  return { id: string(row.id), title: string(row.title), agent_version_id: string(row.agent_version_id) }
}
export async function request<T>(path: string, parse: (value: unknown) => T, init?: RequestInit): Promise<T> {
  const response = await fetch('/api/v1' + path, init)
  const data: unknown = await response.json()
  if (!response.ok) {
    const code = response.status === 403 || response.status === 404 ? '无权访问或内容已不可用' :
      response.status === 503 ? '服务尚未就绪，请检查连接与登录配置' : '请求未完成'
    let detail = ''
    try { detail = string(record(record(data).error).message) } catch { /* keep safe fallback */ }
    throw new Error(detail ? `${code}：${detail}` : code)
  }
  return parse(data)
}
const post = (value: unknown, key?: string): RequestInit => ({ method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) }, body: JSON.stringify(value) })
export const tenantPath = (id: string) => `/tenants/${encodeURIComponent(id)}`
export const runPath = (tenant: string, id: string) => `${tenantPath(tenant)}/runs/${encodeURIComponent(id)}`
export const api = {
  tenants: (signal?: AbortSignal) => request('/tenants', value => array<Tenant>(value, item => {
    const row = record(item); return { id: string(row.id), name: string(row.name) }
  }), { signal }),
  agents: (tenant: string, signal?: AbortSignal) => request(`${tenantPath(tenant)}/agents`, value => array<Agent>(value, item => {
    const row = record(item); return { id: string(row.id), name: string(row.name), runtime_type: string(row.runtime_type), published_version_id: nullable(row.published_version_id) }
  }), { signal }),
  sessions: (tenant: string, signal?: AbortSignal) => request(`${tenantPath(tenant)}/sessions`, value => array(value, parseSession), { signal }),
  createSession: (tenant: string, version: string) => request(`${tenantPath(tenant)}/sessions`, parseSession, post({ agent_version_id: version })),
  history: (tenant: string, session: string, cursor: number, signal?: AbortSignal) => request<History>(`${tenantPath(tenant)}/sessions/${encodeURIComponent(session)}/messages?after_sequence=${cursor}`, value => {
    const row = record(value)
    return { messages: array<Message>(row.messages, value => { const message = record(value); return {
      id: string(message.id), run_id: nullable(message.run_id), sequence: integer(message.sequence), role: string(message.role), content: string(message.content),
    } }), latest_run: row.latest_run === null ? null : parseRun(row.latest_run) }
  }, { signal }),
  send: (tenant: string, session: string, message: string, key: string) => request(`${tenantPath(tenant)}/sessions/${encodeURIComponent(session)}/runs`, parseRun, post({ message }, key)),
  cancel: (tenant: string, run: string) => request(`${runPath(tenant, run)}/cancel`, parseRun, post({})),
  input: (tenant: string, run: string) => request<InputRequest | null>(`${runPath(tenant, run)}/input`, value => {
    if (value === null) return null
    const row = record(value); return { input_request_id: string(row.input_request_id), question: string(row.question), candidates: row.candidates === undefined ? [] : array(row.candidates, string) }
  }),
  respond: (tenant: string, run: string, input: string, response: string, key: string) => request(`${runPath(tenant, run)}/input`, parseRun, post({ input_request_id: input, response }, key)),
}
