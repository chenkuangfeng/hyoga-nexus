import { get, post } from '@nexus-web/core/utils/request'
import type { TenantRole } from '@nexus-web/core/api/tenant/members'

/** 加入申请（企业成员主动申请加入，后端 `space_join_requests` 中 direction=application）。 */
export interface JoinApplication {
  id: string
  user_id: string
  email: string | null
  display_name: string | null
  role: TenantRole
  unit_id: string | null
  message: string | null
  status: string
  created_at: string
}

/** 审批时必须指定部门与角色（部门为必填）。角色只能是 admin、contributor、viewer。 */
export type ApplicationRole = 'admin' | 'contributor' | 'viewer'

/**
 * 列出待审批的加入申请。Backend: GET /api/v1/tenants/:id/join-requests（需要 members:manage）。
 */
export async function listJoinApplications(tenantId: string): Promise<JoinApplication[]> {
  const rows = (await get(`/api/v1/tenants/${tenantId}/join-requests`)) as unknown as JoinApplication[]
  return Array.isArray(rows) ? rows : []
}

/**
 * 批准申请：加入指定部门并授予角色。Backend: POST /api/v1/tenants/:id/join-requests/:application_id/approve。
 */
export async function approveJoinApplication(
  tenantId: string,
  applicationId: string,
  body: { unit_id: string; role: ApplicationRole },
): Promise<void> {
  await post(`/api/v1/tenants/${tenantId}/join-requests/${applicationId}/approve`, body)
}

/**
 * 拒绝申请并说明原因。Backend: POST /api/v1/tenants/:id/join-requests/:application_id/reject。
 */
export async function rejectJoinApplication(
  tenantId: string,
  applicationId: string,
  reason: string,
): Promise<void> {
  await post(`/api/v1/tenants/${tenantId}/join-requests/${applicationId}/reject`, { reason })
}
