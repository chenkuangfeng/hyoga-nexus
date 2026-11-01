/** Organization tree, people and space bindings. Shapes mirror apps/api/src/nexus_api/schemas/orgs.py. */
export interface Org { id: string; name: string; status: string; created_at: string }
export interface OrgNode { id: string; parent_id: string | null; name: string; status: string; member_count: number }
export interface UnitMembership { unit_id: string; unit_name: string; is_primary: boolean }
export interface OrgPerson { user_id: string; display_name: string | null; units: UnitMembership[] }
export interface UserOption { user_id: string; display_name: string | null; username: string | null }
export interface BoundSpace { tenant_id: string; tenant_name: string }
export interface SpaceBindingNode { id: string; parent_id: string | null; name: string; status: string }
export interface SpaceBinding { unit_id: string; unit_name: string; organization_name: string; status: string; nodes: SpaceBindingNode[] }
export interface SpaceOrganization { bindings: SpaceBinding[]; people: OrgPerson[] }
export interface JoinResult { added: string[]; skipped: string[] }
