import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test, { type TestContext } from 'node:test'
import { reactive } from 'vue'
import { fixture } from '@nexus-web/core/test-utils/vueFixture'
import { isMigratedAdminSection } from '../../config/settingsRoute'

const fixtures = new WeakMap<TestContext, ReturnType<typeof fixture>>()
function setup(t: TestContext, path = '/platform/settings', back: unknown = null) {
  const actions: string[] = [], route = reactive({ path, query: { section: 'general' } })
  const ui = reactive({ showSettingsModal: false, settingsInitialSection: 'general', closeSettings: () => actions.push('close'), openSettings: (value: string) => { ui.settingsInitialSection = value } })
  if (!fixtures.has(t)) fixtures.set(t, fixture(t))
  const mounted = fixtures.get(t)!.component(new URL('./Settings.vue', import.meta.url), {
    'vue-router': { useRoute: () => route, useRouter: () => ({ options: { history: { state: { back } } }, back: () => actions.push('back'), replace: (value: unknown) => actions.push(`replace:${typeof value === 'string' ? value : JSON.stringify(value)}`) }) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@/stores/ui': { useUIStore: () => ui },
    '@nexus-web/core/composables/useModalShell': { useModalShell: () => ({ requestClose() {} }) },
    '@/config/settingsRoute': { isMigratedAdminSection },
  })
  return { ...mounted, route, ui, actions }
}

test('账户设置只有三个面板，未知及空间记忆查询回到常规设置', t => {
  const s = setup(t)
  assert.equal(s.vm.groups.length, 1)
  assert.equal(s.vm.groups[0].key, 'account')
  assert.deepEqual(Array.from(s.vm.groups[0].items, (item: { key: string }) => item.key), ['general', 'userprofile', 'mymemory'])
  for (const value of ['models', 'sandbox', 'memory', 'mcp-endpoints', 'skills']) {
    s.route.query.section = value; assert.equal(s.vm.section, 'general')
  }
})

test('关闭直接打开的设置页回到新对话；关闭弹出设置保留底层会话', t => {
  const direct = setup(t); direct.vm.close()
  assert.deepEqual(direct.actions, ['close', 'replace:/platform/creatChat'])
  const overlay = setup(t, '/platform/chat/session'); overlay.vm.close()
  assert.deepEqual(overlay.actions, ['close'])
})

test('关闭设置只返回已知应用内路径，不返回另一个设置地址或外站', t => {
  const known = setup(t, '/platform/settings', '/platform/chat/session'); known.vm.close()
  assert.deepEqual(known.actions, ['close', 'back'])
  for (const back of ['https://example.com', '//example.com', '/login', '/platform/settings?section=general']) {
    const s = setup(t, '/platform/settings', back); s.vm.close()
    assert.deepEqual(s.actions, ['close', 'replace:/platform/creatChat'])
  }
})

test('旧治理书签仅展示说明，不进入导航或加载写页面', t => {
  const s = setup(t)
  for (const section of ['storage', 'vectorstore', 'parser', 'members', 'org-structure']) {
    s.route.query.section = section; assert.equal(s.vm.section, section)
    assert.equal(s.vm.groups[0].items.some((item: { key: string }) => item.key === section), false)
  }
  const source = readFileSync(new URL('./Settings.vue', import.meta.url), 'utf8')
  for (const component of ['OrgStructure', 'TenantMembers', 'StorageBackendSettings', 'VectorStoreSettings', 'NexusMemoryWorkspaceSettings']) assert.equal(source.includes(`import ${component}`), false)
  assert.equal(existsSync(new URL('./NexusMemoryWorkspaceSettings.vue', import.meta.url)), false)
})
