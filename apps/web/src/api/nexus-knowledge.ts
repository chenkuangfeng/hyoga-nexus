/**
 * Nexus knowledge API (apps/api `/api/v1/tenants/{tenant_id}/knowledge*`, openspec 2026-11-06-knowledge-base).
 *
 * K0 provides the capability catalog; later stages add knowledge bases, documents, vector stores and search.
 */
import { get } from '@/utils/request'
import { catalogFromResponse, type CapabilityCatalog } from './nexus-knowledge-capabilities'

export * from './nexus-knowledge-capabilities'

function knowledgePath(tenantId: string): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge`
}

/** The capability catalog of the current build; the same for every space the caller belongs to. */
export async function fetchCapabilities(tenantId: string): Promise<CapabilityCatalog> {
  return catalogFromResponse(await get(`${knowledgePath(tenantId)}/capabilities`))
}
