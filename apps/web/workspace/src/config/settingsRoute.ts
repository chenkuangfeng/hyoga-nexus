/** 设置查询参数及旧集成地址的兼容跳转；不再注册集成导航。 */
type QueryValue = string | number | null | undefined | Array<string | number | null>
export type SettingsRouteQuery = Record<string, QueryValue>
const REMOVED_SETTINGS_SECTIONS = new Set(['assistant', 'system-global', 'model-catalog', 'runtime-queues', 'platform-api-keys', 'system-audit-log', 'ollama', 'weknoracloud', 'browserconnection', 'api', 'cli', 'chrome', 'claw'])

export function agentChannelsPath(agentId: string): string { return `/platform/agents/${encodeURIComponent(agentId)}/channels` }

/** 旧 IM/embed 书签进入指定智能体的渠道；缺少智能体时先进入列表，避免跨资源操作。 */
export function legacyIntegrationLocation(section: unknown, tab?: unknown, agentId?: unknown) {
  if (typeof section !== 'string') return undefined
  const raw = section === 'integrations' ? (typeof tab === 'string' ? tab : 'im') : section.replace(/^integration-/, '')
  if (raw === 'im' || raw === 'embed') {
    return typeof agentId === 'string' && agentId ? { path: agentChannelsPath(agentId), query: { tab: raw } } : { path: '/platform/agents', query: {} }
  }
  if (raw === 'mcpserver') return { path: '/platform/settings', query: { section: 'mcp-endpoints' } }
  if (section.startsWith('integration-') || section === 'integrations' || ['api', 'cli', 'chrome', 'claw'].includes(raw)) return { path: '/platform/settings', query: { section: 'general' } }
  return undefined
}

export function normalizeSettingsSection(section: string, tab?: string | null): string {
  if (section === 'mcpserver' || section === 'integration-mcpserver' || (section === 'integrations' && tab === 'mcpserver')) return 'mcp-endpoints'
  if (REMOVED_SETTINGS_SECTIONS.has(section) || section.startsWith('integration-') || ['integrations', 'im', 'embed'].includes(section)) return 'general'
  return section
}
export function buildSettingsRouteQuery(sectionKey: string, currentQuery: object = {}): SettingsRouteQuery {
  const query: SettingsRouteQuery = { ...(currentQuery as SettingsRouteQuery) }
  delete query.tab; delete query.agentId; delete query.panel
  query.section = normalizeSettingsSection(sectionKey)
  return query
}
export function settingsQueryUnchanged(currentQuery: object, nextQuery: SettingsRouteQuery): boolean {
  const current = currentQuery as SettingsRouteQuery
  return String(current.section ?? '') === String(nextQuery.section ?? '') && current.tab == null && nextQuery.tab == null && current.agentId == null && nextQuery.agentId == null && current.panel == null && nextQuery.panel == null
}
