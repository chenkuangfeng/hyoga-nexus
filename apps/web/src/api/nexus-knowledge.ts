/**
 * Nexus knowledge API (apps/api `/api/v1/tenants/{tenant_id}/knowledge*`, openspec 2026-11-06-knowledge-base).
 *
 * K0 provides the capability catalog; later stages add knowledge bases, documents, vector stores and search.
 */
import { get, post } from '@/utils/request'
import { catalogFromResponse, type CapabilityCatalog } from './nexus-knowledge-capabilities'

export * from './nexus-knowledge-capabilities'

function knowledgePath(tenantId: string): string {
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge`
}

/** The capability catalog of the current build; the same for every space the caller belongs to. */
export async function fetchCapabilities(tenantId: string): Promise<CapabilityCatalog> {
  return catalogFromResponse(await get(`${knowledgePath(tenantId)}/capabilities`))
}

// ---------------------------------------------------------------- graph (openspec 2026-11-06-knowledge-base K2)

export type GraphBuildState = 'pending' | 'running' | 'ready' | 'failed' | 'superseded' | 'cancelled'

export interface GraphBuildView {
  id: string
  state: GraphBuildState
  stage: string
  progress: Record<string, unknown>
  mode: string
  entity_count: number
  relation_count: number
  community_count: number
  error: string | null
}

export interface GraphStatus {
  enabled: boolean
  config: { mode: string, store: string, model_id: string | null, entity_types: string[], relation_types: string[],
    instructions: string }
  /** The build search currently uses. */
  ready: GraphBuildView | null
  /** The newest build that is not the visible one (running, pending or failed). */
  latest: GraphBuildView | null
}

export interface GraphNode { id: string, name: string, type: string, description: string, degree: number }
export interface GraphEdge { id: string, source: string, target: string, description: string, keywords: string[], weight: number }
export interface GraphOverview {
  nodes: GraphNode[]
  edges: GraphEdge[]
  communities: Array<{ id: string, level: number, title: string, summary: string, size: number }>
  truncated: boolean
  build: GraphBuildView | null
}

export interface GraphStoreEngine {
  engine: string
  name: string
  status: 'available' | 'planned'
  stage: string | null
  verified: boolean
  builtin: boolean
}

function basesPath(tenantId: string, kbId: string): string {
  return `${knowledgePath(tenantId)}/bases/${encodeURIComponent(kbId)}`
}

export function fetchGraphStatus(tenantId: string, kbId: string): Promise<GraphStatus> {
  return get(`${basesPath(tenantId, kbId)}/graph`) as unknown as Promise<GraphStatus>
}

export function rebuildGraph(tenantId: string, kbId: string): Promise<GraphBuildView> {
  return post(`${basesPath(tenantId, kbId)}/graph/rebuild`, {}) as unknown as Promise<GraphBuildView>
}

export function fetchGraphOverview(tenantId: string, kbId: string, names: string[] = [], hops = 1): Promise<GraphOverview> {
  const query = new URLSearchParams({ hops: String(hops) })
  if (names.length) query.set('names', names.join(','))
  return get(`${basesPath(tenantId, kbId)}/graph/overview?${query}`) as unknown as Promise<GraphOverview>
}

export async function listGraphStores(tenantId: string): Promise<GraphStoreEngine[]> {
  const res: any = await get(`${knowledgePath(tenantId)}/graph-stores`)
  return res.items || []
}
