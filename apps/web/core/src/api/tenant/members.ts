import { del, get, patch, post } from '@nexus-web/core/utils/request'

// TenantRole：owner / admin / contributor / viewer（与后端 TenantRole 一致）。
export type TenantRole = 'owner' | 'admin' | 'contributor' | 'viewer'

export type TenantMemberStatus = 'active' | 'invited' | 'suspended'

/**
 * 空间成员的页面视图。后端 `GET /tenants/:id/members` 返回 `user_id`、`role`、`status`、
 * `joined_at` 以及用户的 `email`、`username`、`display_name`；这里补齐页面需要的字段。
 */
export interface TenantMember {
  user_id: string
  email: string
  username: string
  display_name?: string | null
  avatar?: string
  role: TenantRole
  status: TenantMemberStatus
  invited_by?: string | null
  joined_at: string
}

export interface ListMembersResponse {
  success: boolean
  data?: {
    members: TenantMember[]
    total: number
    page?: number
    page_size?: number
  }
  message?: string
}

export interface ListMembersParams {
  page?: number
  page_size?: number
  /** 按邮箱 / 用户名 / 显示名筛选（本地过滤：后端一次返回全部成员） */
  q?: string
}

/** 后端成员行（`MemberView`）。 */
interface MemberRow {
  user_id: string
  role: TenantRole
  status: TenantMemberStatus
  joined_at: string
  email?: string | null
  username?: string | null
  display_name?: string | null
}

export interface AddMemberRequest {
  email: string
  role: TenantRole
}

/**
 * 按邮箱添加成员的结果（`POST /tenants/:id/members/by-email`）：
 * - `invited`：已有账号，发出邀请（`invitation_id`），对方接受后才成为成员；
 * - `created`：邮箱没有账号，由管理员设置初始密码创建，已直接加入（`user_id`）。
 */
export interface AddMemberResult {
  status: 'invited' | 'created'
  invitation_id?: string
  user_id?: string
}

export interface AddMemberResponse {
  success: boolean
  data?: AddMemberResult
  message?: string
}

export interface SimpleResponse {
  success: boolean
  message?: string
}

function toTenantMember(row: MemberRow): TenantMember {
  return {
    user_id: row.user_id,
    email: row.email ?? '',
    username: row.username ?? '',
    display_name: row.display_name ?? null,
    role: row.role,
    status: row.status,
    joined_at: row.joined_at,
  }
}

/**
 * 列出空间成员。后端一次返回全部活跃成员，分页与 `q` 筛选在此处完成。
 * Backend: GET /api/v1/tenants/:id/members（需要 members:manage）。
 */
export async function listMembers(
  tenantId: string,
  params: ListMembersParams = {},
): Promise<ListMembersResponse> {
  const rows = (await get<MemberRow[]>(`/api/v1/tenants/${tenantId}/members`)) as unknown as MemberRow[]
  const keyword = params.q?.trim().toLowerCase()
  let members = (Array.isArray(rows) ? rows : []).map(toTenantMember)
  if (keyword) {
    members = members.filter((m) =>
      [m.email, m.username, m.display_name ?? ''].some((v) => v.toLowerCase().includes(keyword)),
    )
  }
  const total = members.length
  const pageSize = params.page_size && params.page_size > 0 ? params.page_size : total
  const page = params.page && params.page > 0 ? params.page : 1
  const start = (page - 1) * pageSize
  return {
    success: true,
    data: { members: members.slice(start, start + pageSize), total, page, page_size: pageSize },
  }
}

/**
 * 遍历分页拉取空间的全部成员。用于「退出空间」等对全量成员的轻量校验。
 */
export async function fetchAllTenantMembers(tenantId: string): Promise<TenantMember[]> {
  const resp = await listMembers(tenantId)
  return resp.data?.members ?? []
}

/**
 * 按邮箱邀请或添加成员（管理员及以上）。
 * Backend: POST /api/v1/tenants/:id/members/by-email。
 * 邮箱没有账号时后端要求提供用户名与初始密码，此处只传邮箱与角色。
 */
export async function addMember(
  tenantId: string,
  body: AddMemberRequest,
): Promise<AddMemberResponse> {
  const result = (await post(`/api/v1/tenants/${tenantId}/members/by-email`, body)) as unknown as AddMemberResult
  return { success: true, data: result }
}

/**
 * 修改成员角色。`userId` 即成员的用户 id（成员行以 (tenant, user) 为主键）。
 * Backend: PATCH /api/v1/tenants/:id/members/:user_id（owner 与 admin 可改；转让 owner 仅 owner）。
 */
export async function updateMemberRole(
  tenantId: string,
  userId: string,
  role: TenantRole,
): Promise<SimpleResponse> {
  await patch(`/api/v1/tenants/${tenantId}/members/${userId}`, { role })
  return { success: true }
}

/**
 * 移出成员。Backend: DELETE /api/v1/tenants/:id/members/:user_id。
 * 移出最后一名 owner 会被拒绝（409）。
 */
export async function removeMember(
  tenantId: string,
  userId: string,
): Promise<SimpleResponse> {
  await del(`/api/v1/tenants/${tenantId}/members/${userId}`)
  return { success: true }
}

/**
 * 自行退出空间（任何活跃成员均可，最后一名 owner 不可退出）。
 * Backend: POST /api/v1/tenants/:id/leave。
 */
export async function leaveTenant(tenantId: string): Promise<SimpleResponse> {
  await post(`/api/v1/tenants/${tenantId}/leave`)
  return { success: true }
}
