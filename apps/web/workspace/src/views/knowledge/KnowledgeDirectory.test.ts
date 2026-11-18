import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

test('知识库目录仅消费读取接口，没有创建或共享操作，切换身份丢弃旧响应', async t => {
  const f = fixture(t), auth = reactive({ effectiveTenantId: 'a', user: { id: 'u' }, currentTenantRole: 'owner' })
  const pending: Array<(value: unknown) => void> = []
  const mounted = f.component(new URL('./KnowledgeBaseList.vue', import.meta.url), {
    'vue-router': { useRouter: () => ({ push() {} }) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    '@nexus-web/core/api/knowledge-base/index': { listKnowledgeBases: () => new Promise(resolve => pending.push(resolve)) },
  })
  auth.effectiveTenantId = 'b'; await flush()
  pending[1]!({ data: [{ id: 'b', name: 'B', can_edit: true }] }); await flush()
  pending[0]!({ data: [{ id: 'a', name: 'A' }] }); await flush()
  assert.equal(mounted.vm.rows[0].id, 'b')
  for (const action of ['handleCreateKnowledgeBase', 'duplicateKB', 'handleDelete', 'handleShare']) assert.equal(mounted.vm[action], undefined)
})
