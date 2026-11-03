import { del, get, post } from '@/utils/request'
import type { TenantMember, TenantRole } from '@/api/tenant/members'

// 邀请只有一种待处理状态：pending。接受、拒绝、撤销后记录即从列表消失（后端不保留历史行）。
export type TenantInvitationStatus = 'pending' | 'accepted' | 'declined' | 'revoked' | 'expired'

/**
 * 页面使用的邀请视图。后端 `GET /tenants/:id/invitations` 返回 `id`、`user_id`、`email`、
 * `display_name`、`role`、`status`、`message`、`created_at`；本模块补齐页面字段。
 */
export interface TenantInvitation {
  id: string
  tenant_id: string
  tenant_name?: string
  invitee_user_id: string
  invitee_email?: string
  invitee_name?: string
  invited_by?: string | null
  inviter_email?: string
  inviter_name?: string
  role: TenantRole
  status: TenantInvitationStatus
  message?: string
  expires_at: string
  responded_at?: string | null
  created_at: string
  // 共享链接相关字段：后端尚未实现邀请链接，这些字段目前恒为空。
  invite_url?: string
  is_share_link?: boolean
  accepted_count?: number
}

export interface ListInvitationsResponse {
  success: boolean
  data?: {
    invitations: TenantInvitation[]
    total: number
    page?: number
    page_size?: number
  }
  message?: string
}

export interface ListTenantInvitationsParams {
  includeTerminal?: boolean
  page?: number
  page_size?: number
}

export interface CreateInvitationRequest {
  email: string
  role: TenantRole
  message?: string
  /** 邮箱没有账号时必填：后端据此创建账号并直接加入空间。 */
  username?: string
  password?: string
}

export interface CreateInvitationResponse {
  success: boolean
  // 邮箱已有账号：返回待接受的邀请（有 id）；邮箱无账号时由管理员创建并直接加入，返回成员（有 user_id）。
  data?: TenantInvitation | TenantMember
  message?: string
}

export interface SimpleResponse {
  success: boolean
  message?: string
}

export interface AcceptInvitationResponse {
  success: boolean
  message?: string
}

export interface AcceptInvitationByTokenResponse {
  success: boolean
  data?: {
    membership: { tenant_id: string; role: TenantRole; status: string; joined_at: string }
    tenant_name?: string
  }
  message?: string
}

export interface PendingCountResponse {
  success: boolean
  data?: { pending_count: number }
  message?: string
}

/** 后端 `_request_view` 的邀请行（空间侧列表）。 */
interface InvitationRow {
  id: string
  user_id: string
  email?: string | null
  display_name?: string | null
  role: TenantRole
  status: TenantInvitationStatus
  message?: string | null
  created_at: string
}

/** 后端 `my_invitations` 的行（被邀请人侧列表）。 */
interface MyInvitationRow {
  id: string
  tenant_id: string
  tenant_name: string
  role: TenantRole
  created_at: string
}

function toInvitation(tenantId: string, row: InvitationRow): TenantInvitation {
  return {
    id: row.id,
    tenant_id: tenantId,
    invitee_user_id: row.user_id,
    invitee_email: row.email ?? '',
    invitee_name: row.display_name ?? '',
    role: row.role,
    status: row.status,
    message: row.message ?? undefined,
    expires_at: '',
    created_at: row.created_at,
  }
}

/**
 * 列出空间的待处理邀请。后端一次返回全部待处理邀请，分页在此处完成。
 * Backend: GET /api/v1/tenants/:id/invitations（需要 members:manage）。
 */
export async function listTenantInvitations(
  tenantId: string,
  options: ListTenantInvitationsParams = {},
): Promise<ListInvitationsResponse> {
  const rows = (await get<InvitationRow[]>(
    `/api/v1/tenants/${tenantId}/invitations`,
  )) as unknown as InvitationRow[]
  const all = (Array.isArray(rows) ? rows : []).map((row) => toInvitation(tenantId, row))
  const total = all.length
  const pageSize = options.page_size && options.page_size > 0 ? options.page_size : total
  const page = options.page && options.page > 0 ? options.page : 1
  const start = (page - 1) * pageSize
  return {
    success: true,
    data: { invitations: all.slice(start, start + pageSize), total, page, page_size: pageSize },
  }
}

/**
 * 邀请一个邮箱。已有账号：发出待接受邀请；没有账号：后端需要用户名与初始密码，
 * 当前界面只收集邮箱与角色，因此这种情况会以 422 提示，待后续补充表单。
 * Backend: POST /api/v1/tenants/:id/members/by-email（需要 members:manage）。
 */
export async function createInvitation(
  tenantId: string,
  body: CreateInvitationRequest,
): Promise<CreateInvitationResponse> {
  const result = (await post(`/api/v1/tenants/${tenantId}/members/by-email`, {
    email: body.email,
    role: body.role,
    username: body.username,
    password: body.password,
  })) as unknown as { status: 'invited' | 'created'; invitation_id?: string; user_id?: string }
  if (result.status === 'created' && result.user_id) {
    const member: TenantMember = {
      user_id: result.user_id,
      email: body.email,
      username: '',
      role: body.role,
      status: 'active',
      joined_at: '',
    }
    return { success: true, data: member }
  }
  return {
    success: true,
    data: {
      id: result.invitation_id ?? '',
      tenant_id: tenantId,
      invitee_user_id: '',
      invitee_email: body.email,
      role: body.role,
      status: 'pending',
      message: body.message,
      expires_at: '',
      created_at: '',
    },
  }
}

/**
 * 撤销待处理邀请。Backend: DELETE /api/v1/tenants/:id/invitations/:invitation_id。
 */
export async function revokeInvitation(tenantId: string, invId: string): Promise<SimpleResponse> {
  await del(`/api/v1/tenants/${tenantId}/invitations/${invId}`)
  return { success: true }
}

/**
 * 列出我收到的待处理邀请。Backend: GET /api/v1/me/invitations。
 * `includeTerminal` 暂不支持：后端只保留待处理邀请。
 */
export async function listMyInvitations(
  _options: { includeTerminal?: boolean } = {},
): Promise<ListInvitationsResponse> {
  const rows = (await get<MyInvitationRow[]>('/api/v1/me/invitations')) as unknown as MyInvitationRow[]
  const invitations: TenantInvitation[] = (Array.isArray(rows) ? rows : []).map((row) => ({
    id: row.id,
    tenant_id: row.tenant_id,
    tenant_name: row.tenant_name,
    invitee_user_id: '',
    role: row.role,
    status: 'pending',
    expires_at: '',
    created_at: row.created_at,
  }))
  return { success: true, data: { invitations, total: invitations.length } }
}

/**
 * 待处理邀请数量（顶部角标轮询）。Backend: GET /api/v1/me/invitations/pending-count。
 */
export async function getMyPendingInvitationCount(): Promise<PendingCountResponse> {
  const body = (await get('/api/v1/me/invitations/pending-count')) as unknown as { count: number }
  return { success: true, data: { pending_count: body.count ?? 0 } }
}

/**
 * 接受我收到的邀请，成为空间成员。Backend: POST /api/v1/me/invitations/:id/accept。
 */
export async function acceptInvitation(invId: string): Promise<AcceptInvitationResponse> {
  await post(`/api/v1/me/invitations/${invId}/accept`)
  return { success: true }
}

/**
 * 拒绝我收到的邀请。Backend: POST /api/v1/me/invitations/:id/decline。
 */
export async function declineInvitation(invId: string): Promise<SimpleResponse> {
  await post(`/api/v1/me/invitations/${invId}/decline`)
  return { success: true }
}

// ---- 待实现（后端尚无对应接口，调用会得到 404）----
// 邀请链接与「用令牌加入」尚未在 Nexus 实现，见 openspec 变更 tasks 第 3、6 组的待办项。

export interface CreateInviteLinkRequest {
  role: TenantRole
  message?: string
}

export interface CreateInviteLinkResponse {
  success: boolean
  data?: TenantInvitation
  message?: string
}

/** 待实现：邀请链接。Backend: POST /api/v1/tenants/:id/invite-links（尚未实现）。 */
export async function createInviteLink(
  tenantId: string,
  body: CreateInviteLinkRequest,
): Promise<CreateInviteLinkResponse> {
  return (await post(
    `/api/v1/tenants/${tenantId}/invite-links`,
    body,
  )) as unknown as CreateInviteLinkResponse
}

/** 待实现：用邀请链接令牌加入。Backend: POST /api/v1/me/invitations/accept-by-token（尚未实现）。 */
export async function acceptInvitationByToken(
  token: string,
): Promise<AcceptInvitationByTokenResponse> {
  return (await post(
    `/api/v1/me/invitations/accept-by-token`,
    { token },
  )) as unknown as AcceptInvitationByTokenResponse
}
