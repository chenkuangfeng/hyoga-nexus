/** 管理导航沿用 WeKnora Settings.vue 分组和资源入口，链接按 Nexus 企业权限过滤。 */
export interface AdminNavigationItem { path: string; label: string; icon: string; permission?: string; roles?: string[] }
export interface AdminNavigationGroup { key: string; label: string; items: AdminNavigationItem[] }
const groups: AdminNavigationGroup[] = [
  { key: 'resources', label: '', items: [
    { path: '/knowledge', label: 'consoleLayout.knowledgeManagement', icon: 'folder', permission: 'enterprise_kbs:manage' },
    { path: '/agents', label: 'consoleLayout.agentManagement', icon: 'app', permission: 'enterprise_agents:manage' },
    { path: '/skills', label: 'consoleLayout.toolbox', icon: 'tools', permission: 'tools:manage' },
  ] },
  { key: 'account', label: 'settings.navGroups.account', items: [
    { path: '/settings', label: 'consoleLayout.settings', icon: 'setting' },
  ] },
  { key: 'workspace', label: 'settings.navGroups.workspace', items: [
    { path: '/enterprise', label: 'consoleLayout.space', icon: 'user-circle', roles: ['owner', 'admin'] },
    { path: '/members', label: 'consoleLayout.members', icon: 'usergroup', permission: 'members:manage' },
    { path: '/organization', label: 'enterpriseLayout.enterpriseOrganization', icon: 'view-organization', permission: 'org:manage' },
    { path: '/roles', label: 'consoleLayout.roles', icon: 'user-safety', permission: 'roles:manage' },
    { path: '/policy', label: 'consoleLayout.policy', icon: 'setting', permission: 'policy:manage' },
  ] },
  { key: 'models_runtime', label: 'settings.navGroups.modelsRuntime', items: [
    { path: '/models', label: 'consoleLayout.modelManagement', icon: 'control-platform', permission: 'models:manage' },
  ] },
  { key: 'integrations', label: 'integrations.title', items: [
    { path: '/channels', label: 'integrations.tabs.im', icon: 'chat-message', permission: 'enterprise_agents:manage' },
    { path: '/mcp-endpoints', label: 'consoleLayout.mcpPublish', icon: 'tools', permission: 'tools:manage' },
    { path: '/wecom', label: 'adminWecom.title', icon: 'link', permission: 'org:manage' },
  ] },
  { key: 'data_extensions', label: 'settings.navGroups.dataExtensions', items: [
    { path: '/vector-stores', label: 'settings.vectorStoreEngine', icon: 'data-base', permission: 'enterprise_kbs:manage' },
    { path: '/parsers', label: 'settings.parserEngine', icon: 'file-search', roles: ['owner', 'admin'] },
    { path: '/storage', label: 'settings.storageEngine', icon: 'cloud', permission: 'enterprise_kbs:manage' },
    { path: '/graph-stores', label: 'consoleLayout.graph', icon: 'chart-bubble', permission: 'enterprise_kbs:manage' },
  ] },
  { key: 'system_administration', label: 'settings.navGroups.systemAdministration', items: [
    { path: '/runtime', label: 'adminRuntime.title', icon: 'queue', roles: ['owner', 'admin'] },
    { path: '/audit', label: 'adminAudit.title', icon: 'history', permission: 'audit:read' },
  ] },
]
/** 展示过滤不替代服务端逐请求鉴权。 */
export function visibleAdminNavigation(role: string, can: (permission: string) => boolean): AdminNavigationGroup[] {
  return groups.map(group => ({ ...group, items: group.items.filter(item =>
    (!item.roles || item.roles.includes(role)) && (!item.permission || can(item.permission))) })).filter(group => group.items.length)
}
