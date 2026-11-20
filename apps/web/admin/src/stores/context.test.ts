import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { fixture } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0], fetch: (tenant: string) => Promise<string[]>) {
  const auth = vue.reactive({ effectiveTenantId: 'a', user: { id: 'user' }, currentEntries: ['admin'], currentTenantRole: 'owner' })
  pinia.setActivePinia(pinia.createPinia())
  const compiled = fixture(t).evaluate(readFileSync(new URL('./context.ts', import.meta.url), 'utf8'), {
    vue, pinia, '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    '@nexus-web/core/api/enterprise-connections': { fetchConnectionPermissions: fetch },
  })
  const context = compiled.useAdminContext()
  t.after(() => context.$dispose())
  return { auth, context }
}

test('管理权限取自服务端；owner 名称不能代替 policy:manage', async t => {
  const { context } = setup(t, async () => [])
  await context.load()
  assert.equal(context.ready, true)
  assert.equal(context.can('policy:manage'), false)
})

test('企业切换立即清权限，旧请求不能恢复；管理入口撤销同样失效', async t => {
  let finish: (apis: string[]) => void = () => {}
  const { auth, context } = setup(t, () => new Promise(resolve => { finish = resolve }))
  const pending = context.load()
  auth.effectiveTenantId = 'b'
  finish(['policy:manage']); await pending
  assert.equal(context.ready, false)
  assert.equal(context.can('policy:manage'), false)
  const next = context.load()
  finish(['policy:manage']); await next
  assert.equal(context.can('policy:manage'), true)
  auth.currentEntries = []
  assert.equal(context.ready, false)
  assert.equal(context.permissions.length, 0)
})

test('同企业切换账号会同步清除权限，失败请求保持不可写', async t => {
  let fail = false
  const { auth, context } = setup(t, async () => { if (fail) throw new Error('offline'); return ['policy:manage'] })
  await context.load()
  auth.user = { id: 'other' }
  assert.equal(context.can('policy:manage'), false)
  fail = true; await context.load()
  assert.equal(context.failed, true)
  assert.equal(context.can('policy:manage'), false)
})

test('切页仅保留侧栏权限，校验结果、失败和企业切换立即更新菜单', async t => {
  let apis = ['policy:manage']
  let fail = false
  const { auth, context } = setup(t, async () => {
    if (fail) throw new Error('offline')
    return apis
  })
  const options = { preserveNavigation: true }
  await context.load()
  context.invalidate(options)
  assert.equal(context.can('policy:manage'), false)
  assert.equal(context.hasNavigationPermission('policy:manage'), true)

  apis = ['audit:read']
  await context.load(options)
  assert.equal(context.hasNavigationPermission('policy:manage'), false)
  assert.equal(context.hasNavigationPermission('audit:read'), true)

  fail = true
  await context.load(options)
  assert.equal(context.hasNavigationPermission('audit:read'), false)
  assert.equal(context.ready, false)

  fail = false
  await context.load()
  context.invalidate(options)
  auth.effectiveTenantId = 'b'
  assert.equal(context.hasNavigationPermission('audit:read'), false)
})
