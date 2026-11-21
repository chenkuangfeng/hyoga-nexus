/** 企业侧栏六组固定顺序。链接可见性由当前企业权限决定。 */
export interface AdminNavigationItem { path: string; label: string; icon: string; permission?: string; roles?: string[] }
export interface AdminNavigationGroup { key: string; label: string; items: AdminNavigationItem[] }
const groups: AdminNavigationGroup[] = [
  { key: 'configuration', label: 'enterpriseNav.configuration', items: [
    { path: '/models', label: 'consoleLayout.models', icon: 'control-platform', permission: 'models:manage' },
    { path: '/knowledge', label: 'consoleLayout.knowledge', icon: 'folder', permission: 'enterprise_kbs:manage' },
    { path: '/tools', label: 'enterpriseNav.tools', icon: 'tools', permission: 'tools:manage' },
    { path: '/agents', label: 'consoleLayout.agents', icon: 'app', permission: 'enterprise_agents:manage' },
  ] },
  { key: 'workspace', label: 'settings.navGroups.workspace', items: [
    { path: '/enterprise', label: 'consoleLayout.space', icon: 'user-circle', roles: ['owner', 'admin'] },
    { path: '/policy', label: 'consoleLayout.policy', icon: 'setting', permission: 'policy:manage' },
  ] },
  { key: 'integrations', label: 'integrations.title', items: [
    { path: '/mcp-endpoints', label: 'enterpriseNav.mcp', icon: 'tools', permission: 'tools:manage' },
    { path: '/channels', label: 'integrations.tabs.im', icon: 'chat-message', permission: 'enterprise_agents:manage' },
  ] },
  { key: 'data_extensions', label: 'settings.navGroups.dataExtensions', items: [
    { path: '/vector-stores', label: 'enterpriseNav.vector', icon: 'data-base', permission: 'enterprise_kbs:manage' },
    { path: '/parsers', label: 'settings.parserEngine', icon: 'file-search', roles: ['owner', 'admin'] },
    { path: '/storage', label: 'settings.storageEngine', icon: 'cloud', permission: 'enterprise_kbs:manage' },
    { path: '/sandbox', label: 'enterpriseNav.sandbox', icon: 'code', roles: ['owner', 'admin'] },
    { path: '/graph-stores', label: 'consoleLayout.graph', icon: 'chart-bubble', permission: 'enterprise_kbs:manage' },
  ] },
  { key: 'permissions', label: 'consoleLayout.permissions', items: [
    { path: '/organization', label: 'enterpriseLayout.enterpriseOrganization', icon: 'view-organization', permission: 'org:manage' },
    { path: '/members', label: 'enterpriseNav.users', icon: 'usergroup', permission: 'members:manage' },
    { path: '/roles', label: 'enterpriseNav.roles', icon: 'user-safety', permission: 'roles:manage' },
  ] },
  { key: 'system', label: 'consoleLayout.system', items: [
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
