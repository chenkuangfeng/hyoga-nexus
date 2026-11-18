import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '../test-utils/vueFixture'

for (const { delayed, newer } of [{ delayed: false, newer: false }, { delayed: true, newer: false }, { delayed: true, newer: true }]) {
  test(`卸载编辑器清理路由，延迟导航=${delayed}，随后打开其他编辑器=${newer}`, async t => {
    const f = fixture(t), route = vue.reactive({ path: '/agents', query: {} as Record<string, string> })
    const mode = vue.ref('route'), visible = vue.ref(true)
    let finish = () => {}, closes = 0
    const router = {
      push: (target: { query: Record<string, string> }) => new Promise<void>(resolve => {
        const apply = () => { route.query = target.query; resolve() }
        if (delayed) finish = apply; else apply()
      }),
      replace: async (target: { query: Record<string, string> }) => { route.query = target.query },
    }
    const module = f.evaluate(readFileSync(new URL('./useEditorPresentation.ts', import.meta.url), 'utf8'), {
      vue: { ...vue, inject: () => mode },
      'vue-router': { useRoute: () => route, useRouter: () => router },
      '../stores/auth': { useAuthStore: () => ({}) },
      './preferenceStorage': { loadPreference: () => null, savePreference() {} },
    })
    const mounted = f.mount(vue.defineComponent({ setup() { module.useEditorPresentation(() => visible.value, () => closes++); return {} } }))
    if (!delayed) { await flush(); assert.match(route.query.editor!, /^edit-/) }
    mounted.close()
    if (delayed) finish()
    if (newer) route.query = { editor: 'edit-newer' }
    await flush()
    assert.equal(route.query.editor, newer ? 'edit-newer' : undefined)
    assert.equal(closes, 0)
  })
}
