import { request, tenantPath } from './chat'

/** Snapshot status for one session. `stale` means published memory changed after the snapshot was taken. */
export interface MemorySnapshot { exists: boolean; created_at: string | null; stale: boolean }

const sessionPath = (tenant: string, session: string) => `${tenantPath(tenant)}/sessions/${encodeURIComponent(session)}/memory-snapshot`

export const memorySnapshotApi = {
  status: (tenant: string, session: string, signal?: AbortSignal) => request<MemorySnapshot>(sessionPath(tenant, session), value => {
    const row = value as Record<string, unknown>
    return { exists: row.exists === true, created_at: typeof row.created_at === 'string' ? row.created_at : null, stale: row.stale === true }
  }, { signal }),
  refresh: (tenant: string, session: string) => request<null>(`${sessionPath(tenant, session)}/refresh`, () => null, { method: 'POST' }),
}
