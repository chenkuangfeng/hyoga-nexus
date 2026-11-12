import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test, { type TestContext } from 'node:test'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { fixture } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: TestContext) {
  const f = fixture(t)
  const auth = vue.reactive<{ user: { id: string } | null; effectiveTenantId: string }>({ user: { id: 'a' }, effectiveTenantId: 'enterprise-a' })
  const module = f.evaluate(readFileSync(new URL('./pageDrafts.ts', import.meta.url), 'utf8'), {
    vue, pinia, '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
  })
  const root = pinia.createPinia()
  pinia.setActivePinia(root)
  const drafts = module.usePageDraftStore()
  t.after(() => drafts.$dispose())
  return { auth, drafts }
}

test('工具卡片草稿只交给对应编辑器一次', t => {
  const { drafts } = setup(t)
  drafts.setPageDraft({ kind: 'model', draft: { type: 'chat', model_name: 'example' } })
  assert.equal(drafts.takePageDraft('mcp_service'), null)
  assert.equal(drafts.takePageDraft('model').model_name, 'example')
  assert.equal(drafts.takePageDraft('model'), null)
})
test('同一身份刷新保留草稿，切换企业、账号或退出时同步清空', t => {
  const { auth, drafts } = setup(t)
  const put = () => drafts.setPageDraft({ kind: 'mcp_service', draft: { name: 'Example', transport_type: 'http-streamable', url: 'https://example.test/mcp' } })
  put()
  auth.user = { id: 'a' }
  assert.ok(drafts.pageDraft)
  auth.effectiveTenantId = 'enterprise-b'
  assert.equal(drafts.pageDraft, null)
  put()
  auth.user = { id: 'b' }
  assert.equal(drafts.pageDraft, null)
  put()
  auth.user = null
  assert.equal(drafts.pageDraft, null)
})
