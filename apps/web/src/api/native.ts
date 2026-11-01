/** Validated Native configuration and owned-memory management API; no vendor keys are returned. */
import { request, tenantPath } from './chat'
export type Scalar = string | number | boolean | string[]
export interface NativePreferences { version: number; available_tools: { id: string; label: string; enabled: boolean }[]; can_enable_tools: boolean; settings: Record<string, Record<string, Scalar>>; fields: Record<string, { name: string; label: string; type: string }[]> }
export interface MemoryEntry { id: string; title: string; kind: string; project: string; version: number }
export interface MemoryDraft { id: string; kind: string; diff: string; source_run_id: string }
export interface MemoryData { entries: MemoryEntry[]; drafts: MemoryDraft[] }
export interface MemoryCapture { enabled: boolean; model_profile_version_id: string | null; capacity_policy: 'reject' | 'evict_auto' }
export interface Approval { id: string; tool_name: string; arguments: Record<string, unknown> }
const record = (v: unknown): Record<string, unknown> => { if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('Native 数据格式无效'); return v as Record<string, unknown> }
const str = (v: unknown): string => { if (typeof v !== 'string') throw new Error('Native 数据格式无效'); return v }
const num = (v: unknown): number => { if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error('Native 数值无效'); return v }
const arr = <T>(v: unknown, parse: (value: unknown) => T): T[] => { if (!Array.isArray(v)) throw new Error('Native 列表无效'); return v.map(parse) }
const capture = (value: unknown): MemoryCapture => {
  const row = record(value)
  if (typeof row.enabled !== 'boolean' || (row.capacity_policy !== 'reject' && row.capacity_policy !== 'evict_auto')) throw new Error('自动捕获设置无效')
  return { enabled: row.enabled, model_profile_version_id: row.model_profile_version_id == null ? null : str(row.model_profile_version_id), capacity_policy: row.capacity_policy }
}
const json = (method: string, value?: unknown, key?: string): RequestInit => ({ method, headers: { 'Content-Type': 'application/json', ...(key ? { 'Idempotency-Key': key } : {}) }, ...(value === undefined ? {} : { body: JSON.stringify(value) }) })
const root = (tenant: string) => `${tenantPath(tenant)}/native`
function preferences(value: unknown): NativePreferences {
  const row = record(value), data = record(row.settings), fields = record(row.fields)
  const settings: NativePreferences['settings'] = {}, schema: NativePreferences['fields'] = {}
  for (const [group, values] of Object.entries(data)) {
    settings[group] = {}
    for (const [key, value] of Object.entries(record(values))) {
      if (typeof value === 'string' || typeof value === 'boolean' || typeof value === 'number') settings[group][key] = value
      else settings[group][key] = arr(value, str)
    }
  }
  for (const [group, values] of Object.entries(fields)) schema[group] = arr(values, value => { const item = record(value); return { name: str(item.name), label: str(item.label), type: str(item.type) } })
  return { version: num(row.version), settings, fields: schema, available_tools: arr(row.available_tools || [], value => { const x = record(value); if (typeof x.enabled !== 'boolean') throw new Error('工具状态无效'); return { id: str(x.id), label: str(x.label), enabled: x.enabled } }), can_enable_tools: row.can_enable_tools === true }
}
export const nativeApi = {
  captureSettings: (w: string, signal?: AbortSignal) => request(`${root(w)}/memory-capture`, capture, { signal }),
  saveCapture: (w: string, value: MemoryCapture) => request(`${root(w)}/memory-capture`, capture, json('PUT', { enabled: value.enabled, model_profile_version_id: value.model_profile_version_id, capacity_policy: value.capacity_policy })),
  enableTool: (w: string, name: string) => request(`${tenantPath(w)}/tools/${encodeURIComponent(name)}/enable`, record, json('POST')),
  branch: (w: string, session: string, version: string) => request(`${root(w)}/sessions/${encodeURIComponent(session)}/model-branch`, value => { const row = record(value); return { id: str(row.id), title: str(row.title), agent_version_id: str(row.agent_version_id) } }, json('POST', { model_profile_version_id: version })),
  settings: (w: string, signal?: AbortSignal) => request(`${root(w)}/settings`, preferences, { signal }),
  saveSettings: (w: string, value: NativePreferences) => request(`${root(w)}/settings`, preferences, json('PUT', { settings: value.settings, expected_version: value.version })),
  memory: (w: string, signal?: AbortSignal) => request<MemoryData>(`${root(w)}/memory`, value => { const row = record(value); return {
    entries: arr(row.entries, value => { const x = record(value); return { id: str(x.id), title: str(x.title), kind: str(x.kind), project: str(x.project), version: num(x.version) } }),
    drafts: arr(row.drafts, value => { const x = record(value); return { id: str(x.id), kind: str(x.kind), diff: str(x.diff), source_run_id: str(x.source_run_id) } }),
  } }, { signal }),
  readMemory: (w: string, id: string, version?: number) => request(`${root(w)}/memory/${encodeURIComponent(id)}${version ? '?version=' + version : ''}`, value => { const row = record(value); return { content: str(row.content), version: num(row.version) } }),
  review: (w: string, id: string, value: { approve: boolean; title?: string; project?: string; entry_id?: string; expected_version?: number }) => request(`${root(w)}/memory-drafts/${encodeURIComponent(id)}/review`, record, json('POST', value)),
  archive: (w: string, id: string) => request(`${root(w)}/memory/${encodeURIComponent(id)}`, record, json('DELETE')),
  restore: (w: string, id: string, version: number, expected_version: number) => request(`${root(w)}/memory/${encodeURIComponent(id)}/restore`, record, json('POST', { version, expected_version })),
  steer: (w: string, run: string, content: string, key: string) => request(`${root(w)}/runs/${encodeURIComponent(run)}/steer`, record, json('POST', { content }, key)),
  approvals: (w: string, run: string) => request(`${root(w)}/runs/${encodeURIComponent(run)}/approvals`, value => arr<Approval>(value, value => { const row = record(value); return { id: str(row.id), tool_name: str(row.tool_name), arguments: record(row.arguments) } })),
  approve: (w: string, run: string, id: string, approve: boolean) => request(`${root(w)}/runs/${encodeURIComponent(run)}/approvals/${encodeURIComponent(id)}`, record, json('POST', { approve })),
}
