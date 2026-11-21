/** 管理导航依用户业务分组；工具箱拆分参照 WeKnora e1f9a6166 Toolbox.vue。 */
export interface AdminNavigationItem { path: string; label: string; icon: string; permission?: string; roles?: string[] }
export interface AdminNavigationGroup { key: string; label: string; icon: string; items: AdminNavigationItem[] }
const groups: AdminNavigationGroup[] = [
  { key: 'enterprise', label: 'consoleLayout.enterprise', icon: 'view-organization', items: [
    { path: '/enterprise', label: 'consoleLayout.space', icon: 'user-circle', roles: ['owner', 'admin'] },
    { path: '/policy', label: 'consoleLayout.policy', icon: 'setting', permission: 'policy:manage' },
    { path: '/organization', label: 'enterpriseLayout.enterpriseOrganization', icon: 'view-organization', permission: 'org:manage' },
  ] },
  { key: 'agents', label: 'consoleLayout.agents', icon: 'app', items: [
    { path: '/agents', label: 'consoleLayout.agentManagement', icon: 'app', permission: 'enterprise_agents:manage' },
  ] },
  { key: 'knowledge', label: 'consoleLayout.knowledge', icon: 'folder', items: [
    { path: '/knowledge', label: 'consoleLayout.knowledgeManagement', icon: 'folder', permission: 'enterprise_kbs:manage' },
  ] },
  { key: 'models', label: 'consoleLayout.models', icon: 'control-platform', items: [
    { path: '/models', label: 'consoleLayout.modelManagement', icon: 'control-platform', permission: 'models:manage' },
  ] },
  { key: 'integrations', label: 'consoleLayout.integrations', icon: 'link', items: [
    { path: '/wecom', label: 'adminWecom.title', icon: 'link', permission: 'org:manage' },
    { path: '/mcp-endpoints', label: 'consoleLayout.mcpPublish', icon: 'link', permission: 'tools:manage' },
  ] },
  { key: 'data_extensions', label: 'consoleLayout.data', icon: 'data-base', items: [
    { path: '/vector-stores', label: 'settings.vectorStoreEngine', icon: 'data-base', permission: 'enterprise_kbs:manage' },
    { path: '/parsers', label: 'settings.parserEngine', icon: 'file-search', roles: ['owner', 'admin'] },
    { path: '/storage', label: 'settings.storageEngine', icon: 'cloud', permission: 'enterprise_kbs:manage' },
    { path: '/graph-stores', label: 'consoleLayout.graph', icon: 'chart-bubble', permission: 'enterprise_kbs:manage' },
  ] },
  { key: 'toolbox', label: 'consoleLayout.toolbox', icon: 'tools', items: [
    { path: '/tools', label: 'consoleLayout.tools', icon: 'tools', permission: 'tools:manage' },
    { path: '/skills', label: 'consoleLayout.skills', icon: 'check-circle', permission: 'tools:manage' },
    { path: '/mcp-services', label: 'consoleLayout.mcpRegister', icon: 'tools', permission: 'tools:manage' },
  ] },
  { key: 'permissions', label: 'consoleLayout.permissions', icon: 'secured', items: [
    { path: '/members', label: 'consoleLayout.members', icon: 'usergroup', permission: 'members:manage' },
    { path: '/roles', label: 'consoleLayout.roles', icon: 'user-safety', permission: 'roles:manage' },
  ] },
  { key: 'system', label: 'consoleLayout.system', icon: 'setting', items: [
    { path: '/settings', label: 'consoleLayout.settings', icon: 'setting' },
    { path: '/runtime', label: 'adminRuntime.title', icon: 'queue', roles: ['owner', 'admin'] },
    { path: '/audit', label: 'adminAudit.title', icon: 'history', permission: 'audit:read' },
  ] },
]
/** 展示过滤不替代服务端逐请求鉴权。 */
export function visibleAdminNavigation(role: string, can: (permission: string) => boolean): AdminNavigationGroup[] {
  return groups.map(group => ({ ...group, items: group.items.filter(item =>
    (!item.roles || item.roles.includes(role)) && (!item.permission || can(item.permission))) })).filter(group => group.items.length)
}
