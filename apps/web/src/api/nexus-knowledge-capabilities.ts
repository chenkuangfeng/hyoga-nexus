/**
 * Knowledge capability catalog (apps/api `GET /api/v1/tenants/{tenant_id}/knowledge/capabilities`).
 *
 * openspec 2026-11-06-knowledge-base K0, decision 5: the web client keeps every WeKnora knowledge feature
 * visible and renders each one from this catalog. `planned` features show a "待实现" badge and cannot be
 * submitted; `available` features with `verified=false` are implemented but not yet checked against a real
 * service (decision 1) and show "未验证". The catalog is the only source of this state, so a feature becomes
 * usable in the UI as soon as the backend marks it available, without front-end changes.
 *
 * Pure types and parsing (no request helpers), so the rules are unit tested without the app's path aliases;
 * `nexus-knowledge.ts` performs the request.
 */
export type CapabilityGroup =
  | 'kb_type' | 'indexing' | 'vector_engine' | 'storage_provider' | 'parser_engine' | 'graph_store'
  | 'graph_mode' | 'datasource' | 'kb_feature'

export interface CapabilityItem {
  group: CapabilityGroup
  key: string
  label: string
  /** Planned stage (K1–K7), or null when not scheduled yet. */
  stage: string | null
  status: 'available' | 'planned'
  verified: boolean
}

export interface CapabilityCatalog {
  items: CapabilityItem[]
  /** Lookup by `group/key`. */
  byKey: Map<string, CapabilityItem>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Parse the endpoint response; malformed items are dropped, a malformed body throws. */
export function catalogFromResponse(data: unknown): CapabilityCatalog {
  if (!isRecord(data) || !Array.isArray(data.items)) throw new Error('Unexpected knowledge capability response')
  const items: CapabilityItem[] = []
  for (const raw of data.items) {
    if (!isRecord(raw) || typeof raw.group !== 'string' || typeof raw.key !== 'string') continue
    items.push({
      group: raw.group as CapabilityGroup,
      key: raw.key,
      label: typeof raw.label === 'string' ? raw.label : raw.key,
      stage: typeof raw.stage === 'string' ? raw.stage : null,
      status: raw.status === 'available' ? 'available' : 'planned',
      verified: raw.verified === true,
    })
  }
  return { items, byKey: new Map(items.map(item => [`${item.group}/${item.key}`, item])) }
}

/** An empty catalog: everything reads as planned until the real catalog loads (fail closed). */
export function emptyCatalog(): CapabilityCatalog {
  return { items: [], byKey: new Map() }
}

/** True only when the backend reports the feature as implemented. Unknown keys count as planned. */
export function isAvailable(catalog: CapabilityCatalog, group: CapabilityGroup, key: string): boolean {
  return catalog.byKey.get(`${group}/${key}`)?.status === 'available'
}

export type CapabilityState =
  | { kind: 'available' }
  | { kind: 'unverified' }
  | { kind: 'planned', stage: string | null }

/**
 * Display state of a feature: `planned` (with its stage) for planned or unknown keys, `unverified` for code
 * not yet checked against a real service, `available` otherwise. Components translate it into a badge.
 */
export function capabilityState(catalog: CapabilityCatalog, group: CapabilityGroup, key: string): CapabilityState {
  const item = catalog.byKey.get(`${group}/${key}`)
  if (!item || item.status === 'planned') return { kind: 'planned', stage: item?.stage ?? null }
  return item.verified ? { kind: 'available' } : { kind: 'unverified' }
}

/** Items of one group in catalog order (for engine/type pickers that list every option). */
export function groupItems(catalog: CapabilityCatalog, group: CapabilityGroup): CapabilityItem[] {
  return catalog.items.filter(item => item.group === group)
}
