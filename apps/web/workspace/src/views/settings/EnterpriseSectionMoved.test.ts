import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
import * as routes from '../../config/settingsRoute'

function setup(t: Parameters<typeof fixture>[0], section: routes.MigratedEnterpriseSection, entries = ['workspace', 'enterprise'], shared?: ReturnType<typeof fixture>) {
  const f = shared || fixture(t), auth = vue.reactive({ currentEntries: entries })
  Object.assign(f.window, { location: { origin: 'http://127.0.0.1:5173' } })
  const source = readFileSync(new URL('./EnterpriseSectionMoved.vue', import.meta.url), 'utf8')
    .replaceAll('import.meta.env.BASE_URL', "'/'").replaceAll('import.meta.env.DEV', 'true')
  const script = compileScript(parse(source).descriptor, { id: 'migration' }).content
    .replace('__expose();', '').replace('return __returned__', '__expose(__returned__); return __returned__')
  // Any unexpected request/client import fails evaluation: the compatibility notice is navigation only.
  const compiled = f.evaluate(script, {
    'vue': vue, 'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '@/config/settingsRoute': routes,
  })
  return { ...f.mount(compiled.default, { section }), auth }
}

test('存储/向量库旧书签指向独立 Admin，无治理请求和自动跳转', async t => {
  const shared = fixture(t)
  for (const [section, target, title] of [['storage', 'storage', 'adminStorage.title'], ['vectorstore', 'vector-stores', 'adminVector.title'], ['parser', 'parsers', 'adminParsers.title']] as const) {
    const s = setup(t, section, undefined, shared); await flush()
    assert.equal(s.vm.destination.titleKey, title)
    assert.equal(s.vm.href, `/enterprise/${target}`)
    assert.equal(s.vm.canOpen, true); s.close()
  }
})
test('切换到没有 Admin 入口的身份后，显式管理链接即时隐藏', async t => {
  const s = setup(t, 'storage'); await flush(); assert.equal(s.vm.canOpen, true)
  s.auth.currentEntries = ['workspace']; await flush(); assert.equal(s.vm.canOpen, false)
  s.auth.currentEntries = ['workspace', 'enterprise']; await flush(); assert.equal(s.vm.canOpen, true)
})
test('部门和成员的兼容链接与独立审计入口保持原目标', async t => {
  const shared = fixture(t)
  const s = setup(t, 'members', undefined, shared); await flush()
  assert.equal(s.vm.members, true); assert.equal(s.vm.auditHref, '/enterprise/audit')
  const org = setup(t, 'org-structure', undefined, shared); await flush(); assert.equal(org.vm.href, '/enterprise/organization')
})
