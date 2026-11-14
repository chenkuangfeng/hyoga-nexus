import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0], authenticated = true) {
  let invalidations = 0, loads = 0, logouts = 0
  const paths: string[] = []
  const auth = reactive({ effectiveTenantId: 'a', currentEntries: ['admin'], memberships: [{ tenant_id: 'a', tenant_name: 'A' }, { tenant_id: 'b', tenant_name: 'B' }],
    setSelectedTenant(id: string) { this.effectiveTenantId = id }, refreshFromAuthMe: async () => authenticated, logout() { logouts++ } })
  const mounted = fixture(t).component(new URL('./AdminLayout.vue', import.meta.url), {
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    './stores/context': { useAdminContext: () => ({ invalidate: () => { invalidations++ }, load: async () => { loads++ } }) },
    '@nexus-web/core/api/auth': { logout: async () => { throw new Error('offline') } },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'vue-router': { useRouter: () => ({ replace: async (path: string) => { paths.push(path) } }) },
  })
  return { ...mounted, auth, paths, invalidations: () => invalidations, loads: () => loads, logouts: () => logouts }
}

test('企业切换只接受成员列表中的企业，重新校准身份后再读取权限', async t => {
  const s = setup(t)
  await s.vm.switchTenant('unknown')
  assert.equal(s.auth.effectiveTenantId, 'a')
  await s.vm.switchTenant('b')
  assert.equal(s.auth.effectiveTenantId, 'b')
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
