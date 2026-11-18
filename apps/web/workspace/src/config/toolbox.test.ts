import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { computed, ref } from 'vue'
import { TOOLBOX_ITEMS, canAccessToolboxSection, isToolboxSection, isToolboxSectionAvailable, toolboxLocation } from './toolbox'
import zhCN from '@nexus-web/core/i18n/locales/zh-CN'

const roles = ['viewer', 'contributor', 'admin', 'owner']
const access = (role: string | null, unsupported: string[] = [], superuser = false) => ({
  currentTenantRole: role,
  canAccessAllTenants: superuser,
  hasRole: (min: string) => roles.indexOf(role || '') >= roles.indexOf(min),
  isSupported: (capability?: string) => !capability || !unsupported.includes(capability),
})

test('toolbox tabs expose skills, tools and MCP; infrastructure stays in settings', () => {
  assert.deepEqual(TOOLBOX_ITEMS.map((item) => [item.key, item.available]),
    [['skills', true], ['tools', true], ['mcp', true]])
  const lookup = (key: string) => key.split('.').reduce<any>((node, part) => node?.[part], zhCN)
  for (const item of TOOLBOX_ITEMS) {
    for (const key of [item.title, item.description]) assert.equal(typeof lookup(key), 'string', key)
  }
  assert.equal(isToolboxSectionAvailable('skills') && isToolboxSectionAvailable('tools'), true)
  assert.equal(isToolboxSectionAvailable('mcp'), true)
  for (const key of ['sandbox', 'websearch', 'envvars', 'integration-api', 'browserconnection', undefined, 'unknown']) {
    assert.equal(isToolboxSection(key), false)
  }
})

test('every active member sees the toolbox; the server decides what they may change', () => {
  for (const role of ['viewer', 'contributor', 'admin', 'owner']) {
    for (const item of TOOLBOX_ITEMS) assert.equal(canAccessToolboxSection(item.key, access(role)), true)
  }
  assert.equal(canAccessToolboxSection('skills', access(null)), false)
  assert.equal(canAccessToolboxSection('skills', access(null, [], true)), true)
  const role = ref('admin')
  const allowed = computed(() => canAccessToolboxSection('skills', access(role.value)))
  assert.equal(allowed.value, true)
  role.value = ''
  assert.equal(allowed.value, false)
})

test('skill shortcut retains its target sandbox without leaking it to other tools', () => {
  assert.deepEqual(toolboxLocation('skills', 'sandbox-123'), {
    path: '/platform/toolbox/skills', query: { sandboxId: 'sandbox-123' },
  })
  assert.deepEqual(toolboxLocation('tools', 'sandbox-123'), {
    path: '/platform/toolbox/tools', query: {},
  })
  assert.deepEqual(toolboxLocation(), { path: '/platform/toolbox', query: {} })
})

test('员工设置只挂载三个账户面板，旧工具箱地址回到对话', () => {
  const settings = readFileSync(new URL('../views/settings/Settings.vue', import.meta.url), 'utf8')
  for (const component of ['GeneralSettings', 'UserProfile', 'NexusMemorySettings']) assert.ok(settings.includes(`<${component}`))
  for (const component of ['SkillSettings', 'McpSettings', 'BrowserConnectionSettings', 'ModelSettings', 'NexusMemoryWorkspaceSettings']) assert.equal(settings.includes(`<${component}`), false)
  const router = readFileSync(new URL('../router/index.ts', import.meta.url), 'utf8')
  assert.match(router, /path: "toolbox\/:section\?", redirect: "\/platform\/creatChat"/)
  assert.equal(router.includes('views/toolbox/NexusToolbox.vue'), false)
  const menu = readFileSync(new URL('../stores/menu.ts', import.meta.url), 'utf8')
  const source = menu.slice(menu.indexOf('reactive<MenuItem[]>('), menu.indexOf('const isFirstSession'))
  assert.deepEqual([...source.matchAll(/path: '([^']+)'/g)].map(match => match[1]), ['creatChat', 'knowledge-bases', 'agents'])
})
