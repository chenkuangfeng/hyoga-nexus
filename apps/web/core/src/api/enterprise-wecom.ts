/** 当前企业企微绑定和自建应用目录，所有秘密字段只写不读。 */
import { get, put, post } from '../utils/request'

export interface WecomApp { id: string; name: string; purpose: 'workspace' | 'admin' | 'agent'; status: 'active' | 'disabled'; qr_login: boolean; entry_path: string; wecom_agentid: string; nexus_agent_id: string | null }
export interface WecomConfig { configured: boolean; corp_id: string | null; callback_configured: boolean; callback_path: string | null; sync_status: string | null; sync_error: string | null; synced_at: string | null; apps: WecomApp[] }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('admin_response_invalid'); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('admin_response_invalid'); return value }
function nullable(value: unknown): string | null { return value === null ? null : string(value) }
function parseApp(value: unknown): WecomApp {
  const row = object(value), purpose = string(row.purpose), status = string(row.status)
  if (!['workspace', 'admin', 'agent'].includes(purpose) || !['active', 'disabled'].includes(status) || typeof row.qr_login !== 'boolean') throw new Error('admin_response_invalid')
  return { id: string(row.id), name: string(row.name), purpose: purpose as WecomApp['purpose'], status: status as WecomApp['status'], qr_login: row.qr_login, entry_path: string(row.entry_path), wecom_agentid: string(row.wecom_agentid), nexus_agent_id: nullable(row.nexus_agent_id) }
}
function parseConfig(value: unknown): WecomConfig {
  const row = object(value)
  if (typeof row.configured !== 'boolean' || !Array.isArray(row.apps)) throw new Error('admin_response_invalid')
  if (!row.configured) return { configured: false, corp_id: null, callback_configured: false, callback_path: null, sync_status: null, sync_error: null, synced_at: null, apps: [] }
  if (typeof row.callback_configured !== 'boolean') throw new Error('admin_response_invalid')
  return { configured: true, corp_id: string(row.corp_id), callback_configured: row.callback_configured, callback_path: string(row.callback_path), sync_status: string(row.sync_status), sync_error: nullable(row.sync_error), synced_at: nullable(row.synced_at), apps: row.apps.map(parseApp) }
}
function path(tenantId: string): string { return `/api/v1/tenants/${encodeURIComponent(tenantId)}/admin/wecom` }
/** 获取企微绑定、回调配置状态、同步状态和应用目录。 */
export async function getEnterpriseWecom(tenantId: string): Promise<WecomConfig> { return parseConfig(await get(path(tenantId))) }
/** 创建企业绑定或更新回调凭据；空凭据不覆盖服务器已保存的值。 */
export async function saveEnterpriseWecom(tenantId: string, input: { corp_id: string; callback_token?: string; encoding_aes_key?: string }): Promise<WecomConfig> {
  return parseConfig(await put(path(tenantId), input))
}
/** 请求 worker 立即同步企业通讯录。 */
export async function requestEnterpriseWecomSync(tenantId: string): Promise<void> {
  const row = object(await post(`${path(tenantId)}/sync`, {}))
  if (row.queued !== true) throw new Error('admin_response_invalid')
}
