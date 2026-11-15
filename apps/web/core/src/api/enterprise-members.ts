/** 企业成员管理的真实 Nexus 契约。与旧工作台适配器分开，避免迁移时改变其响应形状。 */
import { del, get, patch, post } from '../utils/request'

export type MemberRole = 'owner' | 'admin' | 'contributor' | 'viewer'
export type InviteRole = Exclude<MemberRole, 'owner'>
export interface EnterpriseMember {
  tenant_id: string; user_id: string; role: MemberRole; status: 'active'; joined_at: string
  email: string | null; username: string | null; display_name: string | null
}
interface InvitationBase { id: string; role: InviteRole; status: 'pending'; created_at: string }
export interface PersonInvitation extends InvitationBase { kind: 'person'; user_id: string; email: string | null; display_name: string | null }
export interface LinkInvitation extends InvitationBase { kind: 'link'; invite_path: string; expires_at: string; accepted_count: number }
export type EnterpriseInvitation = PersonInvitation | LinkInvitation
export interface MemberEmailInput { email: string; role: InviteRole; username?: string; password?: string; display_name?: string }
export type MemberEmailResult = { status: 'invited'; invitation_id: string } | { status: 'created'; user_id: string }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('members_response_invalid'); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('members_response_invalid'); return value }
function nullable(value: unknown): string | null { return value == null ? null : string(value) }
function role(value: unknown): MemberRole { const text = string(value); if (!['owner', 'admin', 'contributor', 'viewer'].includes(text)) throw new Error('members_response_invalid'); return text as MemberRole }
function inviteRole(value: unknown): InviteRole { const parsed = role(value); if (parsed === 'owner') throw new Error('members_response_invalid'); return parsed }
function tenantAdminPath(id: string): string { return `/api/v1/tenants/${encodeURIComponent(id)}/admin` }
/** 仅接受当前成员列表契约的 active 记录；不得把缺失字段转成默认授权状态。 */
export function memberFromResponse(value: unknown): EnterpriseMember {
  const row = object(value)
  if (row.status !== 'active') throw new Error('members_response_invalid')
  return { tenant_id: string(row.tenant_id), user_id: string(row.user_id), role: role(row.role), status: 'active', joined_at: string(row.joined_at), email: nullable(row.email), username: nullable(row.username), display_name: nullable(row.display_name) }
}
/** 邀请链接仅可指向已知加入页，拒绝外部地址或夹带额外参数的响应。 */
export function invitationFromResponse(value: unknown): EnterpriseInvitation {
  const row = object(value)
  if (row.status !== 'pending' || (row.is_share_link !== undefined && typeof row.is_share_link !== 'boolean')) throw new Error('members_response_invalid')
  const base: InvitationBase = { id: string(row.id), role: inviteRole(row.role), status: 'pending', created_at: string(row.created_at) }
  if (row.is_share_link === true) {
    const path = string(row.invite_url), count = row.accepted_count
    if (!/^\/join\?token=[A-Za-z0-9_-]{1,128}$/.test(path) || typeof count !== 'number' || !Number.isSafeInteger(count) || count < 0) throw new Error('members_response_invalid')
    return { ...base, kind: 'link', invite_path: path, expires_at: string(row.expires_at), accepted_count: count }
  }
  return { ...base, kind: 'person', user_id: string(row.user_id), email: nullable(row.email), display_name: nullable(row.display_name) }
}
/** 服务端一次返回全部活跃成员，搜索和分页由页面完成；拒绝跨企业响应。 */
export async function listEnterpriseMembers(tenantId: string): Promise<EnterpriseMember[]> {
  const data: unknown = await get(`${tenantAdminPath(tenantId)}/members`)
  if (!Array.isArray(data)) throw new Error('members_response_invalid')
  const rows = data.map(memberFromResponse)
  if (rows.some(row => row.tenant_id !== tenantId)) throw new Error('members_response_invalid')
  return rows
}
/** 返回待处理人员邀请和未过期链接。链接仅供当前管理页面短时持有，不写入存储。 */
export async function listEnterpriseInvitations(tenantId: string): Promise<EnterpriseInvitation[]> {
  const data: unknown = await get(`${tenantAdminPath(tenantId)}/invitations`)
  if (!Array.isArray(data)) throw new Error('members_response_invalid')
  return data.map(invitationFromResponse)
}
/** 邀请已有账号；提供用户名和临时密码时，允许为未注册邮箱创建账号。秘密不进入返回状态。 */
export async function addEnterpriseMember(tenantId: string, input: MemberEmailInput): Promise<MemberEmailResult> {
  const row = object(await post(`${tenantAdminPath(tenantId)}/members/by-email`, input))
  if (row.status === 'invited') return { status: 'invited', invitation_id: string(row.invitation_id) }
  if (row.status === 'created') return { status: 'created', user_id: string(row.user_id) }
  throw new Error('members_response_invalid')
}
/** 改成员基础角色；owner 规则和最后一名 owner 的保护由后端事务复核。 */
export async function changeEnterpriseMemberRole(tenantId: string, userId: string, nextRole: MemberRole): Promise<EnterpriseMember> {
  const row = memberFromResponse(await patch(`${tenantAdminPath(tenantId)}/members/${encodeURIComponent(userId)}`, { role: nextRole }))
  if (row.tenant_id !== tenantId || row.user_id !== userId) throw new Error('members_response_invalid')
  return row
}
/** 移除企业成员资格，不删除账号，不等同于可恢复的停用；调用方须先确认。 */
export async function removeEnterpriseMember(tenantId: string, userId: string): Promise<void> { await del(`${tenantAdminPath(tenantId)}/members/${encodeURIComponent(userId)}`) }
/** 创建 1–30 天的加入链接，任何已登录的持有者可按指定角色加入；不可邀请 owner。 */
export async function createEnterpriseInviteLink(tenantId: string, nextRole: InviteRole, days: number): Promise<LinkInvitation> {
  const row = invitationFromResponse(await post(`${tenantAdminPath(tenantId)}/invite-links`, { role: nextRole, expires_in_days: days }))
  if (row.kind !== 'link') throw new Error('members_response_invalid')
  return row
}
/** 撤销人员邀请或共享邀请链接；调用方须先确认。 */
export async function revokeEnterpriseInvitation(tenantId: string, id: string): Promise<void> { await del(`${tenantAdminPath(tenantId)}/invitations/${encodeURIComponent(id)}`) }

export interface EnterpriseApplication {
  id: string; user_id: string; email: string | null; display_name: string | null
  role: InviteRole; status: 'pending'; unit_id: string | null; message: string | null; created_at: string
}
/** 只消费待处理申请；拒绝已审批状态或 owner 等不符合申请契约的响应。 */
export function applicationFromResponse(value: unknown): EnterpriseApplication {
  const row = object(value)
  if (row.status !== 'pending') throw new Error('members_response_invalid')
  return { id: string(row.id), user_id: string(row.user_id), email: nullable(row.email), display_name: nullable(row.display_name), role: inviteRole(row.role), status: 'pending', unit_id: nullable(row.unit_id), message: nullable(row.message), created_at: string(row.created_at) }
}
/** 列出当前企业待审批申请；需要 members:manage，不包含历史审批记录。 */
export async function listEnterpriseApplications(tenantId: string): Promise<EnterpriseApplication[]> {
  const data: unknown = await get(`${tenantAdminPath(tenantId)}/join-requests`)
  if (!Array.isArray(data)) throw new Error('members_response_invalid')
  return data.map(applicationFromResponse)
}
/** 批准到指定部门和基础角色；校验回执用户与角色，避免把不相符的结果展示为批准成功。 */
export async function approveEnterpriseApplication(tenantId: string, id: string, input: { unit_id: string; role: InviteRole }, expectedUserId: string): Promise<void> {
  const row = object(await post(`${tenantAdminPath(tenantId)}/join-requests/${encodeURIComponent(id)}/approve`, input))
  if (row.status !== 'active' || string(row.user_id) !== expectedUserId || inviteRole(row.role) !== input.role) throw new Error('members_response_invalid')
}
/** 拒绝必须说明原因；后端记录审核与 7 天重新申请冷却期，调用方应在确认表单中说明。 */
export async function rejectEnterpriseApplication(tenantId: string, id: string, reason: string): Promise<void> {
  await post(`${tenantAdminPath(tenantId)}/join-requests/${encodeURIComponent(id)}/reject`, { reason })
}
