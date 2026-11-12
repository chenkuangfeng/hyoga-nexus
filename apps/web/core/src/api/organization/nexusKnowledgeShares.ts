/**
 * Pure mapping between Nexus knowledge-base shares and the WeKnora organization-share shapes the copied pages read
 * (openspec 2026-11-06-knowledge-base K1.9c).
 *
 * Nexus shares a base into a **shared space** (WeKnora's "organization") at a level `viewer | editor | admin`.
 * The pages key a share by `id` and also pass `organization_id`; Nexus removes a share by its shared space id, so the
 * mapped share `id` is the shared space id (unique per base). No request helpers are imported, so the mapping is unit
 * tested without the app's path aliases.
 */

export type ShareLevel = 'admin' | 'editor' | 'viewer'

type Json = Record<string, any>

const LEVELS: readonly ShareLevel[] = ['viewer', 'editor', 'admin']

/** A level from the wire; anything unknown is treated as the least privileged one. */
export function toLevel(value: unknown): ShareLevel {
  return LEVELS.includes(value as ShareLevel) ? value as ShareLevel : 'viewer'
}

/** Body of `POST …/bases/{kb}/shares` for the WeKnora share request. */
export function toNexusShareBody(req: { organization_id: string, permission: string }) {
  return { shared_space_id: req.organization_id, level: toLevel(req.permission) }
}

/** One entry of `GET …/bases/{kb}/shares` or the `POST` answer, in the WeKnora share shape. */
export function toWeKnoraShare(item: Json, kbId: string) {
  const level = toLevel(item.level)
  return {
    id: String(item.shared_space_id ?? ''),
    knowledge_base_id: String(item.kb_id ?? kbId),
    organization_id: String(item.shared_space_id ?? ''),
    organization_name: String(item.shared_space_name ?? ''),
    shared_by_user_id: '',
    source_tenant_id: String(item.owner_tenant_id ?? ''),
    permission: level,
    my_permission: level,
    created_at: String(item.created_at ?? ''),
  }
}

/** `{ shares, total }`, the envelope data of the WeKnora share list. */
export function toWeKnoraShareList(items: unknown, kbId: string) {
  const rows = Array.isArray(items) ? items as Json[] : []
  return { shares: rows.map(row => toWeKnoraShare(row, kbId)), total: rows.length }
}

/** One entry of `GET …/shared-bases` in the WeKnora "shared with me" shape. */
export function toWeKnoraSharedBase(item: Json) {
  const level = toLevel(item.level)
  return {
    knowledge_base: {
      id: String(item.id ?? ''),
      name: String(item.name ?? ''),
      description: String(item.description ?? ''),
      type: String(item.type ?? 'document'),
      knowledge_count: Number(item.knowledge_count ?? 0),
      chunk_count: Number(item.chunk_count ?? 0),
      created_at: item.created_at,
      updated_at: item.updated_at,
    },
    share_id: String(item.id ?? ''),
    organization_id: '',
    org_name: String(item.owner_tenant_name ?? ''),
    permission: level,
    source_tenant_id: String(item.owner_tenant_id ?? ''),
    shared_at: String(item.updated_at ?? item.created_at ?? ''),
  }
}

/**
 * Nexus shared spaces as the organization list the share dialog offers. `my_role` is the caller's space role in the
 * shared space; sharing needs only membership, so every listed space is offered (`is_owner` is set for that).
 */
export function toOrganizationList(spaces: unknown) {
  const rows = Array.isArray(spaces) ? spaces as Json[] : []
  const organizations = rows.map(space => ({
    id: String(space.id ?? ''),
    name: String(space.name ?? ''),
    description: String(space.description ?? ''),
    owner_id: '',
    owner_tenant_id: String(space.owner_tenant_id ?? ''),
    member_count: Number(space.member_count ?? 0),
    is_owner: true,
    my_role: space.role ?? undefined,
    created_at: String(space.created_at ?? ''),
    updated_at: String(space.created_at ?? ''),
  }))
  return { organizations, total: organizations.length }
}
