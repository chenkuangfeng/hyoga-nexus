import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'
import { visibleAdminNavigation } from './navigation'
import { fixture } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0], authenticated = true) {
  let invalidations = 0, loads = 0, logouts = 0
  const paths: string[] = []
  const auth = reactive({ effectiveTenantId: 'a', currentEntries: ['enterprise'], memberships: [{ tenant_id: 'a', tenant_name: 'A' }, { tenant_id: 'b', tenant_name: 'B' }],
    setSelectedTenant(id: string) { this.effectiveTenantId = id }, refreshFromAuthMe: async () => authenticated, logout() { logouts++ } })
  const f = fixture(t)
  const mounted = f.component(new URL('./EnterpriseLayout.vue', import.meta.url), {
    './navigation': { visibleAdminNavigation },
    '@nexus-web/core/composables/useEditorPresentation': { ADMIN_EDITOR_MODE: Symbol('mode'), useAdminEditorPreference: () => ref('modal') },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    './stores/context': { useEnterpriseContext: () => ({ hasNavigationPermission: () => false, invalidate: () => { invalidations++ }, load: async () => { loads++ } }) },
    '@nexus-web/core/api/auth': { logout: async () => { throw new Error('offline') } },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'vue-router': { useRouter: () => ({ replace: async (path: string) => { paths.push(path) } }) },
  })
  return { ...mounted, window: f.window, auth, paths, invalidations: () => invalidations, loads: () => loads, logouts: () => logouts }
}

test('企业切换只接受成员列表中的企业，重新校准身份后再读取权限', async t => {
  const s = setup(t)
  s.vm.toggleMenu('enterprise')
  await s.vm.switchTenant('unknown')
  assert.equal(s.auth.effectiveTenantId, 'a')
  assert.equal(s.vm.expandedMenu, 'enterprise')
  await s.vm.switchTenant('b')
  assert.equal(s.auth.effectiveTenantId, 'b')
  assert.equal(s.vm.expandedMenu, null)
  assert.equal(s.invalidations(), 1)
  assert.equal(s.loads(), 1)
  assert.deepEqual(s.paths, ['/'])
})

test('身份校准失败只进入登录；退出接口失败也会清除本地身份', async t => {
  const s = setup(t, false)
  await s.vm.switchTenant('b')
  assert.equal(s.loads(), 0)
  assert.deepEqual(s.paths, ['/login'])
  await s.vm.signOut()
  assert.equal(s.logouts(), 1)
  assert.equal(s.invalidations(), 3)
  assert.deepEqual(s.paths, ['/login', '/login'])
})


test('折叠状态独立切换，关闭用户弹层可恢复触发按钮焦点', async t => {
  const s = setup(t)
  assert.equal(s.vm.collapsed, false)
  s.vm.toggleSidebar()
  assert.equal(s.vm.collapsed, true)
  s.vm.toggleSidebar()
  assert.equal(s.vm.collapsed, false)
  let focused = false
  s.vm.accountButton = { focus() { focused = true } }
  s.vm.accountOpen = true
  s.vm.closeAccount(true)
  await import('vue').then(vue => vue.nextTick())
  assert.equal(s.vm.accountOpen, false)
  assert.equal(focused, true)
})

test('进入手机宽度自动收起侧栏，允许手动展开且不被同宽 resize 覆盖', async t => {
  const s = setup(t)
  s.vm.accountOpen = true
  s.window.innerWidth = 375; s.window.dispatchEvent(new Event('resize'))
  assert.equal(s.vm.collapsed, true); assert.equal(s.vm.accountOpen, false)
  s.vm.toggleSidebar(); assert.equal(s.vm.collapsed, false)
  s.window.dispatchEvent(new Event('resize')); assert.equal(s.vm.collapsed, false)
  s.window.innerWidth = 1200; s.window.dispatchEvent(new Event('resize'))
  s.window.innerWidth = 375; s.window.dispatchEvent(new Event('resize')); assert.equal(s.vm.collapsed, true)
})
