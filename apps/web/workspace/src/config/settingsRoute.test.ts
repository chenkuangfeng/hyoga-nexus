import assert from 'node:assert/strict'
import test from 'node:test'
import { agentChannelsPath, buildSettingsRouteQuery, legacyIntegrationLocation, normalizeSettingsSection, settingsQueryUnchanged } from './settingsRoute'

test('旧渠道书签保留智能体与 tab，缺少智能体时进入列表', () => {
  assert.deepEqual(legacyIntegrationLocation('integration-im', undefined, 'agent/a'), { path: '/platform/agents/agent%2Fa/channels', query: { tab: 'im' } })
  assert.deepEqual(legacyIntegrationLocation('integrations', 'embed', 'a'), { path: agentChannelsPath('a'), query: { tab: 'embed' } })
  assert.deepEqual(legacyIntegrationLocation('im'), { path: '/platform/agents', query: {} })
  assert.deepEqual(legacyIntegrationLocation('embed', undefined, ['a', 'b']), { path: '/platform/agents', query: {} })
})
test('MCP 旧入口进入设置，已取消的集成不再展示', () => {
  assert.deepEqual(legacyIntegrationLocation('integrations', 'mcpserver'), { path: '/platform/settings', query: { section: 'mcp-endpoints' } })
  for (const section of ['integration-api', 'integration-cli', 'integration-chrome', 'integration-claw', 'integration-unknown']) {
    assert.deepEqual(legacyIntegrationLocation(section), { path: '/platform/settings', query: { section: 'general' } })
    assert.equal(normalizeSettingsSection(section), 'general')
  }
  assert.equal(legacyIntegrationLocation('models'), undefined)
  assert.equal(legacyIntegrationLocation('https://example.test/'), undefined)
})
test('设置地址清除旧集成与平台参数，并保留正常设置', () => {
  assert.deepEqual(buildSettingsRouteQuery('integration-mcpserver', { section: 'integrations', agentId: 'a', tab: 'im', panel: 'users' }), { section: 'mcp-endpoints' })
  for (const key of ['assistant', 'ollama', 'weknoracloud', 'browserconnection', 'system-global', 'model-catalog', 'runtime-queues', 'platform-api-keys', 'system-audit-log']) assert.equal(normalizeSettingsSection(key), 'general')
  assert.equal(normalizeSettingsSection('models'), 'models')
  assert.equal(normalizeSettingsSection('mcp'), 'mcp')
  assert.equal(settingsQueryUnchanged({ section: 'mcp-endpoints' }, { section: 'mcp-endpoints' }), true)
  assert.equal(settingsQueryUnchanged({ section: 'mcp-endpoints', agentId: 'a' }, { section: 'mcp-endpoints' }), false)
})

test('迁移的部门书签有明确管理应用入口，开发与生产链接保留部署边界', async () => {
  const { adminOrganizationLocation, isMigratedAdminSection } = await import('./settingsRoute')
  assert.equal(isMigratedAdminSection('org-structure'), true)
  assert.equal(isMigratedAdminSection('members'), false)
  assert.equal(adminOrganizationLocation('/', 'http://192.0.2.1:5173', true), 'http://192.0.2.1:5174/admin/organization')
  assert.equal(adminOrganizationLocation('/nexus/', 'https://example.test', false), '/nexus/admin/organization')
  assert.equal(adminOrganizationLocation('/', 'https://example.test', false), '/admin/organization')
})

test('旧部门书签只显示已实现的迁移说明，不再受 owner 导航门槛限制', async () => {
  const { isPhase1Section } = await import('./phase1')
  const { SETTINGS_SECTION_MIN_ROLE } = await import('./settingsAccess')
  assert.equal(isPhase1Section('org-structure'), true)
  assert.equal(SETTINGS_SECTION_MIN_ROLE['org-structure'] ?? 'viewer', 'viewer')
})
