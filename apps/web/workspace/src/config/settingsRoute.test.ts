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
