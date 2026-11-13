import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0], list?: (tenant: string) => Promise<unknown[]>) {
  const f = fixture(t), auth = reactive({ effectiveTenantId: 'tenant', user: { id: 'owner' } })
  const row = { id: 'endpoint', tenant_id: 'tenant', name: 'test', description: '', enabled: true, tool_allowlist: [], kb_ids: [], created_by: 'owner' }
  let resolveCreate: (result: unknown) => void = () => {}, mutations = 0
  let confirmation: { onConfirm: () => Promise<void> } | undefined
  const api = {
    ENDPOINT_TOOLS: [], listEndpoints: list || (async () => [row]),
    fetchConnectionPermissions: async () => ['tools:manage'], listEndpointKnowledge: async () => [],
    createEndpoint: () => new Promise(resolve => { resolveCreate = resolve }),
    deleteEndpoint: async () => { mutations++ },
  }
  const mounted = f.component(new URL('./McpEndpointSettings.vue', import.meta.url), {
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    '@nexus-web/core/api/enterprise-connections': api,
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { DialogPlugin: { confirm: (options: typeof confirmation) => { confirmation = options; return { hide() {} } } } },
    '@/composables/useApiBaseUrlDisplay': { useApiBaseUrlDisplay: () => ({ apiBaseUrlDisplay: ref('http://localhost') }) },
    '@/utils/clipboard': { copyWithToast() {} },
    '@/utils/mcpEndpointSnippets': { buildMcpEndpointUrl: () => '/mcp/endpoint', buildHttpClientSnippet: () => '' },
  })
  return { ...mounted, auth, row, finish: () => resolveCreate({ endpoint: row, token: 'secret-once' }), confirm: () => confirmation!.onConfirm(), mutations: () => mutations }
}

test('MCP 新令牌仅短时保留；相同身份刷新保留，切换身份立即清除', async t => {
  const s = setup(t)
  await flush()
  const pending = s.vm.save({ validateResult: true })
  s.finish(); await pending
  assert.equal(s.vm.freshToken, 'secret-once')
  s.auth.user = { id: 'owner' }
  await flush()
  assert.equal(s.vm.freshToken, 'secret-once')
  s.auth.user = { id: 'other' }
  assert.equal(s.vm.freshToken, '')
  assert.equal(s.vm.issuedEndpoint, null)
})

test('旧企业签发的在途结果和确认弹窗不能污染新企业', async t => {
  const s = setup(t)
  await flush()
  s.vm.act(s.row, 'delete')
  const pending = s.vm.save({ validateResult: true })
  s.auth.effectiveTenantId = 'new-tenant'
  s.finish(); await pending; await flush()
  assert.equal(s.vm.freshToken, '')
  await s.confirm()
  assert.equal(s.mutations(), 0)
})

test('卸载后返回的签发结果不恢复令牌', async t => {
  const s = setup(t)
  await flush()
  const pending = s.vm.save({ validateResult: true })
  s.close(); s.finish(); await pending
  assert.equal(s.vm.freshToken, '')
})


test('离开设置时清空令牌，晚到的签发结果不会恢复弹窗', async t => {
  const s = setup(t)
  await flush()
  const pending = s.vm.save({ validateResult: true })
  s.vm.$.props.active = false
  s.finish(); await pending
  assert.equal(s.vm.freshToken, '')
  assert.equal(s.vm.issuedEndpoint, null)
  assert.equal(s.vm.canManage, false)
})


test('企业列表请求晚到时不会覆盖当前企业', async t => {
  let finishOld: (rows: unknown[]) => void = () => {}
  const s = setup(t, tenant => tenant === 'tenant' ? new Promise(resolve => { finishOld = resolve }) : Promise.resolve([]))
  s.auth.effectiveTenantId = 'new-tenant'
  await flush()
  assert.equal(s.vm.endpoints.length, 0)
  finishOld([s.row])
  await flush()
  assert.equal(s.vm.endpoints.length, 0)
})
