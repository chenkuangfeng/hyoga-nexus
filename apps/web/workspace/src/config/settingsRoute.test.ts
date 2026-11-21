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
  const { enterpriseSettingsLocation, isMigratedEnterpriseSection } = await import('./settingsRoute')
  assert.equal(isMigratedEnterpriseSection('org-structure'), true)
  assert.equal(isMigratedEnterpriseSection('members'), true)
  assert.equal(enterpriseSettingsLocation('/'), '/enterprise/')
  assert.equal(enterpriseSettingsLocation('/nexus/', 'organization'), '/nexus/enterprise/organization')
  assert.equal(enterpriseSettingsLocation('/', 'organization'), '/enterprise/organization')
})

test('旧部门书签只显示已实现的迁移说明，不再受 owner 导航门槛限制', async () => {
  const { isPhase1Section } = await import('./phase1')
  const { SETTINGS_SECTION_MIN_ROLE } = await import('./settingsAccess')
  assert.equal(isPhase1Section('org-structure'), true)
  assert.equal(SETTINGS_SECTION_MIN_ROLE['org-structure'] ?? 'viewer', 'viewer')
})

test('旧企业信息书签迁到个人资料的企业成员身份，清除旧管理参数', () => {
  assert.equal(normalizeSettingsSection('tenant'), 'userprofile')
  assert.deepEqual(buildSettingsRouteQuery('tenant', { section:'tenant',panel:'delete',tab:'members' }), { section:'userprofile' })
})

test('旧 /platform/tenant 实际路由落到账户资料，保留成员身份入口', async () => {
  const { readFileSync } = await import('node:fs')
  const { runInNewContext } = await import('node:vm')
  const ts = await import('typescript')
  const { createRouter, createMemoryHistory } = await import('vue-router')
  const source = readFileSync(new URL('../router/index.ts', import.meta.url),'utf8')
  const ast = ts.createSourceFile('router.ts',source,ts.ScriptTarget.Latest,true)
  let record: string | undefined
  function visit(node: import('typescript').Node) {
    if (ts.isObjectLiteralExpression(node) && node.properties.some(p => ts.isPropertyAssignment(p) && p.name.getText(ast)==='path' && ts.isStringLiteral(p.initializer) && p.initializer.text==='tenant')) record=node.getText(ast)
    ts.forEachChild(node,visit)
  }
  visit(ast); assert.ok(record)
  const route = runInNewContext(`(${record})`)
  const router = createRouter({ history:createMemoryHistory(), routes:[{path:'/platform',children:[route]},{path:'/platform/settings',component:{render:()=>null}}] })
  await router.push('/platform/tenant')
  assert.equal(router.currentRoute.value.path,'/platform/settings')
  assert.equal(router.currentRoute.value.query.section,'userprofile')
})

test('旧成员管理书签属于迁移说明，管理端成员和审计链接保持独立应用地址', async () => {
 const {isMigratedEnterpriseSection,enterpriseSettingsLocation}=await import('./settingsRoute')
 assert.equal(isMigratedEnterpriseSection('members'),true)
 assert.equal(enterpriseSettingsLocation('/','members'),'/enterprise/members')
 assert.equal(enterpriseSettingsLocation('/nexus/','audit'),'/nexus/enterprise/audit')
 assert.equal(normalizeSettingsSection('members'),'members')
})

test('存储与向量库旧书签保留迁移说明，目标仅来自固定枚举', async () => {
 const { isMigratedEnterpriseSection, MIGRATED_ENTERPRISE_SECTIONS, enterpriseSettingsLocation } = await import('./settingsRoute')
 for (const section of ['storage', 'vectorstore', 'parser'] as const) {
   assert.equal(isMigratedEnterpriseSection(section), true)
   assert.equal(normalizeSettingsSection(section), section)
   assert.deepEqual(buildSettingsRouteQuery(section, { tab: 'old', panel: 'write', unrelated: 'keep' }), { section, unrelated: 'keep' })
   const target = MIGRATED_ENTERPRISE_SECTIONS[section].target
   assert.equal(enterpriseSettingsLocation('/nexus/', target), `/nexus/enterprise/${target}`)
 }
 for (const invalid of ['__proto__', 'constructor', 'https://evil.test/', 'vectorstore/../../']) assert.equal(isMigratedEnterpriseSection(invalid), false)
})
