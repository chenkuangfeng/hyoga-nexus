import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { runInNewContext } from 'node:vm'

function setup(response: unknown) {
  const calls: Array<{ verb: string; url: string; input: unknown }> = []
  const request = (verb: string) => async (url: string, input?: unknown) => { calls.push({ verb, url, input }); return response }
  const exports: Record<string, any> = {}
  runInNewContext(ts.transpileModule(readFileSync(new URL('./enterprise-connections.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
    exports, require: (name: string) => { assert.equal(name, '../utils/request'); return { get: request('GET'), post: request('POST'), patch: request('PATCH'), del: request('DELETE') } },
  })
  return { api: exports, calls }
}
const channel = { id: 'c', agent_id: 'agent/a', kind: 'wechat', status: 'binding', name: 'WeChat', owner_user_id: 'owner', bound: false, review_note: null }
const endpoint = { id: 'ep', tenant_id: 'tenant/a', name: 'readonly', description: '', enabled: true, created_by: 'owner', tool_allowlist: ['search_knowledge'], kb_ids: [] }

test('渠道和 MCP 请求使用租户路径、记录 ID 与真实字段', async () => {
  const channels = setup({ items: [channel], unverified_kinds: ['qq', 'wecom_bot'] })
  assert.equal((await channels.api.listAgentChannels('tenant/a', 'agent/a')).items[0].id, 'c')
  assert.equal(channels.calls[0].url, '/api/v1/tenants/tenant%2Fa/agents/agent%2Fa/channels')
  const create = setup(channel)
  await create.api.createAgentChannel('tenant/a', 'agent/a', { kind: 'wechat', name: 'Mine' })
  assert.deepEqual(create.calls[0].input, { kind: 'wechat', name: 'Mine' })
  const patch = setup(endpoint)
  await patch.api.updateEndpoint('tenant/a', 'ep/?', { tool_allowlist: ['search_knowledge'], kb_ids: [] })
  assert.equal(patch.calls[0].verb, 'PATCH')
  assert.equal(patch.calls[0].url, '/api/v1/tenants/tenant%2Fa/mcp-endpoints/ep%2F%3F')
})
test('拒绝错误响应及跨作用域记录，令牌不会混入列表状态', async () => {
  const { api } = setup({ ...endpoint, token: 'secret-once' })
  assert.equal(Object.hasOwn(api.endpointFromResponse({ ...endpoint, token: 'secret-once' }), 'token'), false)
  assert.equal((await api.createEndpoint('tenant/a', {})).token, 'secret-once')
  assert.throws(() => api.channelFromResponse({ ...channel, bound: 'false' }), /connection_response_invalid/)
  assert.throws(() => api.channelFromResponse({ ...channel, status: 'unknown' }), /connection_response_invalid/)
  await assert.rejects(setup([{ ...endpoint, tenant_id: 'other' }]).api.listEndpoints('tenant/a'), /connection_response_invalid/)
  await assert.rejects(setup({ items: [{ ...channel, agent_id: 'other' }], unverified_kinds: [] }).api.listAgentChannels('tenant/a', 'agent/a'), /connection_response_invalid/)
})
test('前端只读工具选择与后端白名单一致', () => {
  const source = readFileSync(new URL('../../../../../packages/platform/src/nexus_platform/mcp/common.py', import.meta.url), 'utf8')
  const block = source.match(/READ_ONLY_TOOL_NAMES = frozenset\(\{([\s\S]*?)\}\)/)![1]
  const names = [...block.matchAll(/"([a-z_]+)"/g)].map(item => item[1]).sort()
  assert.deepEqual(Array.from(setup(null).api.ENDPOINT_TOOLS as string[]).sort(), names)
})
