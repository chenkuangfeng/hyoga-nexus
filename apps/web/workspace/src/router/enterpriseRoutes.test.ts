import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter, type Router, type RouterOptions } from 'vue-router'
import { legacyIntegrationLocation } from '../config/settingsRoute.ts'
import { isToolboxSection, toolboxLocation } from '../config/toolbox.ts'

type Guard = (to: { path: string; fullPath: string; meta: Record<string, boolean>; query: object }, from: object, next: (target?: unknown) => void) => Promise<void>

function setup(options: { token?: string; authenticated?: boolean; restored?: boolean; mustChangePassword?: boolean } = {}) {
  let guard: Guard | undefined
  let refreshes = 0
  const auth = {
    token: '', refreshToken: '', isLoggedIn: options.authenticated ?? false, hasValidTenant: true,
    user: { must_change_password: options.mustChangePassword ?? false },
    setToken(value: string) { this.token = value }, setRefreshToken(value: string) { this.refreshToken = value },
    async refreshFromAuthMe() { refreshes++; this.isLoggedIn = options.restored ?? false; return this.isLoggedIn },
  }
  const dependencies: Record<string, unknown> = {
    vue: { defineComponent },
    'vue-router': {
      createWebHistory: createMemoryHistory,
      createRouter(config: RouterOptions) {
        const router = createRouter(config)
        const register = router.beforeEach
        router.beforeEach = handler => { guard = handler as Guard; return register(handler) }
        return router
      },
    },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    '@/stores/deploymentCapabilities': { useDeploymentCapabilitiesStore: () => ({ ensureLoaded: async () => {}, isSupported: () => true }) },
    '@/config/settingsRoute': { legacyIntegrationLocation }, '@/config/toolbox': { isToolboxSection, toolboxLocation },
    'tdesign-vue-next': { MessagePlugin: { warning() {} } },
    '@nexus-web/core/i18n/index': { default: { global: { t: (key: string) => key } } },
    '@/views/placeholder/PlannedPage.vue': { default: {} },
  }
  const source = readFileSync(new URL('./index.ts', import.meta.url), 'utf8')
    .replaceAll('import.meta.env.BASE_URL', "'/'").replaceAll('import.meta.env.DEV', 'false')
  const exports: { default?: Router } = {}
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, {
    exports, console, window: { location: { hash: '' } },
    localStorage: { getItem: (key: string) => key === 'weknora_token' ? options.token ?? null : null },
    require(name: string) { assert.ok(name in dependencies, `Unexpected route dependency: ${name}`); return dependencies[name] },
  })
  assert.ok(exports.default)
  async function navigate(path: string) {
    assert.ok(guard)
    const resolved = exports.default!.resolve(path)
    const destinations: unknown[] = []
    await guard({ ...resolved, meta: resolved.meta as Record<string, boolean> }, {}, target => destinations.push(target))
    return destinations
  }
  return { router: exports.default, navigate, refreshes: () => refreshes }
}

test('旧平台管理地址落到公共 404，工作台与企业成员设置路由继续可用', () => {
  const { router } = setup()
  for (const path of ['/platform-admin', '/platform/system', '/platform/system/settings', '/platform/system/admins', '/platform/system/queues']) {
    assert.equal(router.resolve(path).matched.at(-1)?.path, '/:pathMatch(.*)*')
  }
  assert.equal(router.resolve('/platform/chat/session-a').name, 'chat')
  assert.equal(router.resolve('/platform/settings?section=members').name, 'settings')
})
test('未登录访问受保护页面进入登录页，不再尝试桌面自动开户', async () => {
  const fixture = setup()
  assert.deepEqual(await fixture.navigate('/platform/agents'), ['/login'])
  assert.equal(fixture.refreshes(), 0)
})
test('已有令牌先恢复身份；恢复失败进入登录页', async () => {
  const valid = setup({ token: 'existing-token', restored: true })
  assert.deepEqual(await valid.navigate('/platform/agents'), ['/platform/agents'])
  assert.equal(valid.refreshes(), 1)
  const expired = setup({ token: 'expired-token' })
  assert.deepEqual(await expired.navigate('/platform/agents'), ['/login'])
  assert.equal(expired.refreshes(), 1)
})
test('改密入口要求认证，临时密码账号不能绕过改密进入工作台', async () => {
  assert.deepEqual(await setup().navigate('/auth/change-password'), ['/login'])
  const temporary = setup({ authenticated: true, mustChangePassword: true })
  assert.deepEqual(await temporary.navigate('/platform/agents'), ['/auth/change-password'])
  assert.deepEqual(await temporary.navigate('/auth/change-password'), [undefined])
})
