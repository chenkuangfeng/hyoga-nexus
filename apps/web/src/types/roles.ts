/** Tenant role contracts. Keys must match the backend catalog (authz/catalog.py). */
export const AGENT_PERMISSIONS = ['view', 'run', 'edit', 'publish', 'manage'] as const
export type AgentPermission = typeof AGENT_PERMISSIONS[number]

export const agentPermissionLabels: Record<AgentPermission, string> = {
  view: '查看', run: '运行', edit: '编辑草稿', publish: '发布', manage: '管理',
}

export const menuLabels: Record<string, string> = {
  chat: '对话工作台', agents: '智能体', models: '模型设置', audit: '审计', members: '成员管理', roles: '角色与权限',
}

export const apiLabels: Record<string, string> = {
  'agents:read': '查看智能体', 'agents:write': '创建智能体', 'agents:publish': '发布智能体',
  'sessions:write': '新建会话', 'runs:write': '发起运行', 'models:read': '查看模型',
  'models:manage': '管理模型与凭据', 'audit:read': '查看审计', 'members:manage': '管理成员',
  'roles:manage': '管理角色', 'tools:manage': '管理工具',
}

export interface PermissionCatalog { menus: string[]; apis: string[] }
export interface Permissions { menus: string[]; apis: string[] }
export interface TenantRole { id: string; tenant_id: string; name: string; menus: string[]; apis: string[] }
export interface TenantMember { tenant_id: string; user_id: string; role: 'owner' | 'admin' | 'member'; status: string }
export interface RoleAssignment { user_id: string; role_id: string }
export interface AgentGrantRow { role_id: string; agent_id: string; permission: AgentPermission }
