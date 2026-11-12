import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import ts from 'typescript'
import { createMemoryHistory, createRouter, type NavigationGuard, type Router } from 'vue-router'

test('管理入口的邀请和开户转交工作台，并保留原始参数', () => {
  const redirects: string[] = []
  const source = readFileSync(new URL('./router.ts', import.meta.url), 'utf8')
    .replaceAll('import.meta.env.BASE_URL', "'/admin/'")
  const exports: { default?: Router } = {}
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, {
    exports, window: { location: { replace: (target: string) => redirects.push(target) } },
    require(name: string) {
      if (name === 'vue-router') return { createRouter, createWebHistory: createMemoryHistory }
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
