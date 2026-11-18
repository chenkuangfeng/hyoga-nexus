import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

test('员工智能体只查看和使用已发布版本，并丢弃切换企业前的响应', async t => {
  const f = fixture(t), auth = reactive({ effectiveTenantId: 'a', user: { id: 'u' }, currentTenantRole: 'owner' })
  const paths: unknown[] = [], warnings: string[] = []
  const pending: Array<(rows: unknown[]) => void> = []
  const mounted = f.component(new URL('./NexusAgentList.vue', import.meta.url), {
    'vue-router': { useRouter: () => ({ push: (path: unknown) => paths.push(path) }) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    'tdesign-vue-next': { MessagePlugin: { warning: (message: string) => warnings.push(message) } },
    '@nexus-web/core/api/nexus-agents': { listNexusAgents: async () => new Promise(resolve => pending.push(resolve)) },
  })
  auth.effectiveTenantId = 'b'; await flush()
  pending[1]!([{ id: 'b', name: 'B', status: 'published', published_version_id: 'bv' }]); await flush()
  pending[0]!([{ id: 'a', name: 'A' }]); await flush()
  assert.equal(mounted.vm.agents[0].id, 'b')
  mounted.vm.useAgent(mounted.vm.agents[0])
  assert.equal(JSON.stringify(paths), JSON.stringify([{ path: '/platform/creatChat', query: { agent: 'bv' } }]))
  mounted.vm.useAgent({ id: 'draft', status: 'draft' })
  assert.equal(paths.length, 1); assert.equal(warnings.length, 1)
  for (const action of ['openCreate', 'openEdit', 'handleCopy', 'handleDelete', 'openChannels']) assert.equal(mounted.vm[action], undefined)
})
