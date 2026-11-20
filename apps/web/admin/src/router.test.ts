import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import { createMemoryHistory, createRouter, type NavigationGuard, type Router } from 'vue-router'

test('管理入口的邀请和开户转交工作台，并保留原始参数', () => {
  const redirects: string[] = []
  const source = readFileSync(new URL('./router.ts', import.meta.url), 'utf8')
    .replaceAll('import.meta.env.BASE_URL', "'/admin/'").replaceAll('import.meta.env.DEV', 'false')
  const exports: { default?: Router } = {}
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, {
    exports, window: { location: { replace: (target: string) => redirects.push(target) } },
    require(name: string) {
      if (name === 'vue-router') return { createRouter, createWebHistory: createMemoryHistory }
      if (name === './stores/context') return { useAdminContext: () => ({ load: async () => {} }) }
      if (name === '@nexus-web/core/stores/auth') return { useAuthStore: () => ({}) }
      assert.fail(`Unexpected admin route dependency: ${name}`)
    },
  })
  assert.ok(exports.default)
  const router = exports.default
  for (const path of ['/join?token=invite%2Btoken', '/onboarding/workspace?from=admin']) {
    const to = router.resolve(path)
    const record = to.matched.at(-1)
    assert.equal(record?.meta.public, true)
    assert.equal(typeof record?.beforeEnter, 'function')
    const enter = record!.beforeEnter as NavigationGuard
    assert.equal(enter(to, to, () => {}), false)
  }
  assert.deepEqual(redirects, ['/join?token=invite%2Btoken', '/onboarding/workspace?from=admin'])
  assert.equal(router.resolve('/missing').matched.at(-1)?.path, '/:pathMatch(.*)*')
})

test('受保护路由先作废旧权限、校准身份，强制改密优先于加载业务权限', async () => {
  const events: string[] = []
  let guard: (to: { meta: { public?: boolean }; path: string }) => Promise<unknown> = async () => false
  let token: string | null = 'token'
  const auth = { user: { must_change_password: false }, refreshFromAuthMe: async () => { events.push('auth'); return true } }
  const source = readFileSync(new URL('./router.ts', import.meta.url), 'utf8').replaceAll('import.meta.env.BASE_URL', "'/admin/'").replaceAll('import.meta.env.DEV', 'false')
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
    exports: {}, localStorage: { getItem: () => token },
    require(name: string) {
      if (name === 'vue-router') return { createWebHistory: () => null, createRouter: () => ({ beforeEach: (fn: typeof guard) => { guard = fn } }) }
      if (name === '@nexus-web/core/stores/auth') return { useAuthStore: () => auth }
      if (name === './stores/context') return { useAdminContext: () => ({
        invalidate: (options?: { preserveNavigation: boolean }) => events.push(options?.preserveNavigation ? 'invalidate-business' : 'invalidate'),
        load: async (options?: { preserveNavigation: boolean }) => { events.push(options?.preserveNavigation ? 'permissions-preserving-navigation' : 'permissions') },
      }) }
      assert.fail(`Unexpected dependency: ${name}`)
    },
  })
  assert.equal(await guard({ meta: {}, path: '/policy' }), true)
  assert.deepEqual(events, ['invalidate-business', 'auth', 'permissions-preserving-navigation'])
  events.length = 0; auth.user.must_change_password = true
  assert.equal(await guard({ meta: {}, path: '/policy' }), '/auth/change-password')
  assert.deepEqual(events, ['invalidate-business', 'auth', 'invalidate'])
  events.length = 0; token = null
  assert.equal(await guard({ meta: {}, path: '/' }), '/login')
  assert.deepEqual(events, ['invalidate'])
})


test('管理外壳不提供工作台跳转参数，开户入口保留独立转交', () => {
  const redirects: string[] = []
  const source = readFileSync(new URL('./router.ts', import.meta.url), 'utf8').replaceAll('import.meta.env.BASE_URL', "'/admin/'").replaceAll('import.meta.env.DEV', 'true')
  const exports: { default?: Router } = {}
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
    exports, URL, window: { location: { origin: 'http://192.0.2.1:5174', replace: (url: string) => redirects.push(url) } },
    require(name: string) {
      if (name === 'vue-router') return { createRouter, createWebHistory: createMemoryHistory }
      if (name === '@nexus-web/core/stores/auth') return { useAuthStore: () => ({}) }
      if (name === './stores/context') return { useAdminContext: () => ({}) }
      assert.fail(`Unexpected dependency: ${name}`)
    },
  })
  const router = exports.default!
  const to = router.resolve('/join?token=invite%2Btoken')
  const enter = to.matched.at(-1)!.beforeEnter as NavigationGuard
  enter(to, to, () => {})
  assert.deepEqual(redirects, ['http://192.0.2.1:5173/join?token=invite%2Btoken'])
  assert.equal(router.resolve('/').matched[0].props.default, false)
})
