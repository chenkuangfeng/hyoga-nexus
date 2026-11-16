/** 分组及顺序来自 WeKnora e1f9a6166 Settings.vue；Nexus 入口归入同用途的原版分组。 */
export interface AdminNavigationItem { path: string; label: string; icon: string; permission?: string; roles?: string[] }
export interface AdminNavigationGroup { key: string; label: string; items: AdminNavigationItem[] }
const groups: AdminNavigationGroup[] = [
  { key: 'workspace', label: 'settings.navGroups.workspace', items: [
    { path: '/enterprise', label: 'adminNavigation.info', icon: 'user-circle', roles: ['owner'] },
    { path: '/members', label: 'adminMembers.title', icon: 'usergroup', permission: 'members:manage' },
    { path: '/organization', label: 'adminOrganization.title', icon: 'view-organization', permission: 'org:manage' },
    { path: '/roles', label: 'adminRoles.title', icon: 'user-safety', permission: 'roles:manage' },
    { path: '/policy', label: 'adminNavigation.policy', icon: 'setting', permission: 'policy:manage' },
    { path: '/agents', label: 'adminNavigation.agents', icon: 'app', permission: 'enterprise_agents:manage' },
    { path: '/knowledge', label: 'adminNavigation.knowledge', icon: 'folder', permission: 'enterprise_kbs:manage' },
    { path: '/usage', label: 'adminUsage.title', icon: 'chart-bar', permission: 'models:manage' },
  ] },
  { key: 'models_runtime', label: 'settings.navGroups.modelsRuntime', items: [
    { path: '/models', label: 'settings.modelManagement', icon: 'control-platform', permission: 'models:manage' },
  ] },
  { key: 'integrations', label: 'integrations.title', items: [
    { path: '/wecom', label: 'adminWecom.title', icon: 'link', permission: 'org:manage' },
    { path: '/channels', label: 'adminChannels.title', icon: 'chat', permission: 'enterprise_agents:manage' },
    { path: '/mcp-endpoints', label: 'connectionUi.endpoints', icon: 'link', permission: 'tools:manage' },
  ] },
  { key: 'data_extensions', label: 'settings.navGroups.dataExtensions', items: [
    { path: '/vector-stores', label: 'settings.vectorStoreEngine', icon: 'data-base', permission: 'enterprise_kbs:manage' },
    { path: '/parsers', label: 'settings.parserEngine', icon: 'file-search', roles: ['owner', 'admin'] },
    { path: '/storage', label: 'settings.storageEngine', icon: 'cloud', permission: 'enterprise_kbs:manage' },
    { path: '/graph-stores', label: 'adminNavigation.graph', icon: 'chart-bubble', permission: 'enterprise_kbs:manage' },
    { path: '/mcp-services', label: 'mcpSettings.title', icon: 'tools', permission: 'tools:manage' },
    { path: '/tools', label: 'adminNavigation.tools', icon: 'tools', permission: 'tools:manage' },
    { path: '/skill-submissions', label: 'adminSkillReview.title', icon: 'check-circle', permission: 'tools:manage' },
  ] },
  { key: 'system_administration', label: 'adminNavigation.systemAdministration', items: [
    { path: '/runtime', label: 'adminRuntime.title', icon: 'queue', roles: ['owner', 'admin'] },
    { path: '/audit', label: 'adminAudit.title', icon: 'history', permission: 'audit:read' },
  ] },
  { key: 'platform', label: 'settings.navGroups.platform', items: [
    { path: '/', label: 'adminConsole.overview', icon: 'home' },
  ] },
]
/** 入口展示沿用各路由原有规则；筛选后移除空组，服务端仍逐请求鉴权。 */
export function visibleAdminNavigation(role: string, can: (permission: string) => boolean): AdminNavigationGroup[] {
  return groups.map(group => ({ ...group, items: group.items.filter(item =>
    (!item.roles || item.roles.includes(role)) && (!item.permission || can(item.permission))) })).filter(group => group.items.length)
}
