import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildSettingsRouteQuery,
  integrationSectionKey,
  isIntegrationSection,
  normalizeSettingsSection,
  settingsQueryUnchanged,
} from './settingsRoute'

test('settings nav drops obsolete platform panels and normalizes removed sections', () => {
  assert.deepEqual(
    buildSettingsRouteQuery('models', {
      section: 'system-global',
      tab: 'im',
      agentId: 'agt_1',
    }),
    { section: 'models' },
  )
  assert.deepEqual(
    buildSettingsRouteQuery('general', { section: 'system-global' }),
    { section: 'general' },
  )
  assert.deepEqual(
    buildSettingsRouteQuery('runtime-queues', { section: 'system-global' }),
    { section: 'general' },
  )
  assert.deepEqual(
    buildSettingsRouteQuery('system-global', { section: 'system-global', panel: 'users', tab: 'im' }),
    { section: 'general' },
  )
  assert.deepEqual(
    buildSettingsRouteQuery('models', { section: 'system-global', panel: 'users' }),
    { section: 'models' },
  )
  assert.deepEqual(
    buildSettingsRouteQuery('system-global', { section: 'system-global', panel: 'billing' }),
    { section: 'general' },
  )
  assert.deepEqual(
    buildSettingsRouteQuery(integrationSectionKey('claw'), {
      section: 'integrations',
      tab: 'im',
    }),
    { section: 'integration-claw' },
  )
  assert.deepEqual(
    buildSettingsRouteQuery(integrationSectionKey('api'), {
      section: 'integrations',
      tab: 'im',
      agentId: 'agt_1',
    }),
    { section: 'integration-api', agentId: 'agt_1' },
  )
})

test('legacy api / integrations / bare-tab query strings normalize to nav keys', () => {
  assert.equal(normalizeSettingsSection('api'), 'integration-api')
  assert.equal(normalizeSettingsSection('claw'), 'integration-claw')
  assert.equal(normalizeSettingsSection('cli'), 'integration-cli')
  assert.equal(normalizeSettingsSection('mcpserver'), 'integration-mcpserver')
  // 'mcp' is the MCP-client settings page, not the MCP server integration tab.
  assert.equal(normalizeSettingsSection('mcp'), 'mcp')
  assert.equal(normalizeSettingsSection('integrations', 'cli'), 'integration-cli')
  assert.equal(normalizeSettingsSection('integrations', 'embed'), 'integration-embed')
  assert.equal(normalizeSettingsSection('integrations'), 'integration-im')
  assert.equal(normalizeSettingsSection('integration-chrome'), 'integration-chrome')
  for (const section of ['system-global', 'model-catalog', 'runtime-queues', 'platform-api-keys', 'system-audit-log']) {
    assert.equal(normalizeSettingsSection(section), 'general')
  }
  assert.equal(isIntegrationSection('integration-chrome'), true)
  assert.equal(isIntegrationSection('integration-cli'), true)
  assert.equal(isIntegrationSection('models'), false)
  assert.equal(isIntegrationSection('integration-unknown'), false)
})

test('canonical settings query skips a redundant replace', () => {
  assert.equal(
    settingsQueryUnchanged(
      { section: 'integration-claw' },
      { section: 'integration-claw' },
    ),
    true,
  )
  assert.equal(
    settingsQueryUnchanged(
      { section: 'integrations', tab: 'claw' },
      { section: 'integration-claw' },
    ),
    false,
  )
  assert.equal(
    settingsQueryUnchanged(
      { section: 'system-global', panel: 'users' },
      { section: 'system-global', panel: 'access' },
    ),
    false,
  )
})
