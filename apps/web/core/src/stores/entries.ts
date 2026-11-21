import type { AppEntry, MembershipInfo } from '../api/auth'

/** 按当前企业读取服务端应用入口；无成员身份或旧响应缺失 entries 时关闭入口。 */
export function entriesForTenant(memberships: readonly MembershipInfo[], tenantId: string): AppEntry[] {
  const entries = memberships.find(row => String(row.tenant_id) === tenantId)?.entries
  if (!Array.isArray(entries)) return []
  return entries.filter((entry): entry is AppEntry => entry === 'workspace' || entry === 'enterprise')
}
