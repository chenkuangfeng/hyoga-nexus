/** Tenant role contracts. Keys must match the backend catalog (authz/catalog.py). */
export const AGENT_PERMISSIONS = ['view', 'run', 'edit', 'publish', 'manage'] as const
export type AgentPermission = typeof AGENT_PERMISSIONS[number]

/** Labels are i18n keys under `roleSettings`; views translate them with `$t`/`t`. */
export const agentPermissionLabels: Record<AgentPermission, string> = {
  view: 'roleSettings.perm.view', run: 'roleSettings.perm.run', edit: 'roleSettings.perm.edit', publish: 'roleSettings.perm.publish', manage: 'roleSettings.perm.manage',
}

export const menuLabels: Record<string, string> = {
  chat: 'roleSettings.menu.chat', agents: 'roleSettings.menu.agents', models: 'roleSettings.menu.models', audit: 'roleSettings.menu.audit', members: 'roleSettings.menu.members', roles: 'roleSettings.menu.roles',
}

export const apiLabels: Record<string, string> = {
  'agents:read': 'roleSettings.api.agentsRead', 'agents:write': 'roleSettings.api.agentsWrite', 'agents:publish': 'roleSettings.api.agentsPublish',
  'sessions:write': 'roleSettings.api.sessionsWrite', 'runs:write': 'roleSettings.api.runsWrite', 'models:read': 'roleSettings.api.modelsRead',
  'models:manage': 'roleSettings.api.modelsManage', 'audit:read': 'roleSettings.api.auditRead', 'members:manage': 'roleSettings.api.membersManage',
  'roles:manage': 'roleSettings.api.rolesManage', 'tools:manage': 'roleSettings.api.toolsManage',
}

export interface PermissionCatalog { menus: string[]; apis: string[] }
export interface Permissions { menus: string[]; apis: string[] }
export interface TenantRole { id: string; tenant_id: string; name: string; menus: string[]; apis: string[] }
export interface TenantMember { tenant_id: string; user_id: string; role: 'owner' | 'admin' | 'member'; status: string }
export interface RoleAssignment { user_id: string; role_id: string }
export interface AgentGrantRow { role_id: string; agent_id: string; permission: AgentPermission }
