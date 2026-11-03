/**
 * Shared spaces (WeKnora organizations, named "shared spaces" in Nexus).
 *
 * Every call acts for the caller's current space; the request layer sends it as `X-Tenant-ID`.
 * Endpoints mirror `/api/v1/shared-spaces` in the backend (openspec 2026-11-03, section 4).
 */
import { del, get, post, put } from '@/utils/request'

export type SharedRole = 'admin' | 'editor' | 'viewer'

export interface SharedSpaceSummary {
  id: string
  name: string
  description?: string | null
  role: SharedRole | null
  owner_tenant_id: string
  member_count: number
  created_at: string
}

export interface SharedSpaceMember {
  tenant_id: string
  tenant_name: string
  role: SharedRole
}

export interface SharedSpaceDetail extends SharedSpaceSummary {
  require_approval: boolean
  searchable: boolean
  member_limit: number
  invite_code_validity_days: number
  invite_code?: string | null
  members: SharedSpaceMember[]
}

export interface SharedSpaceJoinRequest {
  id: string
  tenant_id: string
  tenant_name: string
  request_type: 'join' | 'upgrade'
  prev_role: SharedRole | null
  requested_role: SharedRole
  message: string | null
  created_at: string
}

export interface SharedSpaceUpdate {
  name?: string
  description?: string
  require_approval?: boolean
  searchable?: boolean
  member_limit?: number
  invite_code_validity_days?: number
}

export const listSharedSpaces = () => get<SharedSpaceSummary[]>('/api/v1/shared-spaces')

export const createSharedSpace = (body: { name: string; description?: string }) =>
  post<{ id: string; name: string; description?: string | null; owner_tenant_id: string }>('/api/v1/shared-spaces', body)

export const searchSharedSpaces = (q: string) =>
  get<Array<{ id: string; name: string; description?: string | null; member_count: number }>>(
    '/api/v1/shared-spaces/search',
    { params: { q } },
  )

export const previewInviteCode = (code: string) =>
  get<{ id: string; name: string; description?: string | null; member_count: number; require_approval: boolean }>(
    `/api/v1/shared-spaces/preview/${encodeURIComponent(code)}`,
  )

export const joinByInviteCode = (invite_code: string) =>
  post<{ status: 'joined' | 'pending'; shared_space_id?: string; request_id?: string; role?: SharedRole }>(
    '/api/v1/shared-spaces/join',
    { invite_code },
  )

export const joinById = (shared_space_id: string) =>
  post<{ status: 'joined' | 'pending'; request_id?: string }>('/api/v1/shared-spaces/join-by-id', { shared_space_id })

export const getSharedSpace = (id: string) => get<SharedSpaceDetail>(`/api/v1/shared-spaces/${id}`)

export const updateSharedSpace = (id: string, body: SharedSpaceUpdate) =>
  put(`/api/v1/shared-spaces/${id}`, body)

export const deleteSharedSpace = (id: string) => del(`/api/v1/shared-spaces/${id}`)

export const leaveSharedSpace = (id: string) => post(`/api/v1/shared-spaces/${id}/leave`, {})

export const requestUpgrade = (id: string, requested_role: SharedRole, message = '') =>
  post(`/api/v1/shared-spaces/${id}/request-upgrade`, { requested_role, message })

export const regenerateInviteCode = (id: string) =>
  post<{ invite_code: string; expires_at: string }>(`/api/v1/shared-spaces/${id}/invite-code`, {})

export const listJoinRequests = (id: string) =>
  get<SharedSpaceJoinRequest[]>(`/api/v1/shared-spaces/${id}/join-requests`)

export const approveJoinRequest = (id: string, requestId: string) =>
  post(`/api/v1/shared-spaces/${id}/join-requests/${requestId}/approve`, {})

export const rejectJoinRequest = (id: string, requestId: string, review_message: string) =>
  post(`/api/v1/shared-spaces/${id}/join-requests/${requestId}/reject`, { review_message })
