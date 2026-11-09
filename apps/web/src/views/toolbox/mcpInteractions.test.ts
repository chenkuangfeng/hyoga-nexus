import assert from 'node:assert/strict'
import test, { type TestContext } from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '../../test-utils/vueFixture.ts'
import type { McpService, McpServiceTool } from '@/api/nexus-mcp'
import {
  configFromForm, enabledToolNames, formFromService, serviceTarget, validateMcpForm,
} from './toolboxMcp.ts'

const service = (over: Partial<McpService> = {}): McpService => ({
  id: 's1',
  tenant_id: 't1',
  name: 'GitHub',
  description: '',
  transport: 'streamable_http',
  config: { transport: 'streamable_http', timeout: 30, auth_type: 'none', url: 'https://example.com/mcp' },
  enabled: true,
  config_epoch: 'e1',
  created_by: 'u1',
  created_at: '2026-11-09T00:00:00Z',
  updated_at: '2026-11-09T00:00:00Z',
  ...over,
})

const tool = (over: Partial<McpServiceTool> = {}): McpServiceTool => ({
  tool_name: 'echo',
  description: '',
  enabled: true,
  read_only_hint: true,
  catalog_status: 'ready',
  catalog_error: null,
  explicit_risk: null,
  observed_risk: null,
  effective_risk: 'read',
  require_approval: false,
  pending_downgrade: false,
  ...over,
})

/** Mount the toolbox MCP panel with the given API mock; `perms` selects the `tools:manage` grant. */
function panel(t: TestContext, api: Record<string, unknown>, perms: string[] = ['tools:manage']) {
  const f = fixture(t)
  const { vm } = f.component(new URL('./NexusToolboxMcp.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key, te: () => false }) },
    'tdesign-vue-next': { MessagePlugin: { success() {}, error() {} } },
    '@/api/nexus-mcp': api,
    '@/api/nexus-agents': { getMyApiPermissions: async () => perms },
    './toolboxMcp': { enabledToolNames, serviceTarget },
  }, { tenantId: 't1' })
  return vm
}

/** Mount the create/edit dialog with a mocked `@/api/nexus-mcp`. */
function dialog(t: TestContext, api: Record<string, unknown>, serviceProp: McpService | null = null) {
  const f = fixture(t)
  const { vm } = f.component(new URL('./NexusMcpServiceDialog.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@/api/nexus-mcp': api,
    './toolboxMcp': { configFromForm, formFromService, validateMcpForm },
  }, { visible: false, tenantId: 't1', service: serviceProp })
  return vm
}

test('members load the service list without edit affordances', async t => {
  const vm = panel(t, { listMcpServices: async () => [service()] }, [])
  await flush()
  assert.equal(vm.isAdmin, false)
  assert.equal(vm.services.length, 1)
})

test('discovering a service reloads its open tool catalog', async t => {
  let discovered = 0
  const vm = panel(t, {
    listMcpServices: async () => [service()],
    discoverMcpService: async () => { discovered++; return { service_id: 's1', tools: ['echo'], fingerprint: 'f1' } },
    listMcpServiceTools: async () => [tool({ tool_name: 'echo' })],
  })
  await flush()
  vm.openTools = 's1'
  await vm.discover(vm.services[0])
  await flush()
  assert.equal(discovered, 1)
  assert.equal(vm.tools[0].tool_name, 'echo')
})

test('enabling one discovered tool sends the full enabled whitelist', async t => {
  let saved: string[] | undefined
  const vm = panel(t, {
    listMcpServices: async () => [service()],
    setEnabledMcpTools: async (_tid: string, _sid: string, names: string[]) => { saved = names; return names },
  })
  await flush()
  vm.openTools = 's1'
  vm.tools = [tool({ tool_name: 'a' }), tool({ tool_name: 'b', enabled: false })]
  await vm.setToolEnabled(vm.services[0], vm.tools[1], true)
  await flush()
  assert.deepEqual(saved, ['a', 'b'])
})

test('a failed tool toggle rolls the checkbox state back and surfaces the error', async t => {
  const vm = panel(t, {
    listMcpServices: async () => [service()],
    setEnabledMcpTools: async () => { throw new Error('boom') },
  })
  await flush()
  vm.openTools = 's1'
  vm.tools = [tool({ tool_name: 'a' })]
  await vm.setToolEnabled(vm.services[0], vm.tools[0], false)
  await flush()
  assert.equal(vm.tools[0].enabled, true)
  assert.equal(vm.error, 'boom')
})

test('switching a service off patches only its enabled flag', async t => {
  const updates: unknown[] = []
  const s = service()
  const vm = panel(t, {
    listMcpServices: async () => [s],
    updateMcpService: async (_tid: string, _sid: string, body: unknown) => { updates.push(body); return { ...s, enabled: false } },
  })
  await flush()
  await vm.setEnabled(vm.services[0], false)
  await flush()
  assert.equal(updates.length, 1)
  assert.equal((updates[0] as { enabled?: boolean }).enabled, false)
  assert.equal(vm.services[0].enabled, false)
})

test('creating a service posts the normalized connection config', async t => {
  let created: any
  const vm = dialog(t, {
    createMcpService: async (_tid: string, input: unknown) => { created = input; return { id: 'new' } },
  })
  vm.$.props.visible = true
  await vue.nextTick()
  vm.form.name = 'GitHub'
  vm.form.transport = 'streamable_http'
  vm.form.url = 'https://example.com/mcp'
  await vm.save()
  assert.equal(created.name, 'GitHub')
  assert.equal(created.transport, 'streamable_http')
  assert.equal(created.config.url, 'https://example.com/mcp')
  assert.equal(vm.saving, false)
})

test('an empty name blocks submission before any request', async t => {
  let calls = 0
  const vm = dialog(t, { createMcpService: async () => { calls++ } })
  vm.$.props.visible = true
  await vue.nextTick()
  vm.form.name = ''
  vm.form.url = 'https://example.com/mcp'
  await vm.save()
  assert.equal(calls, 0)
  assert.equal(vm.error, 'toolbox.mcp.nameRequired')
})

test('editing an existing service carries the stored OAuth client secret', async t => {
  let updated: any
  const stored = service({
    transport: 'sse',
    config: {
      transport: 'sse', timeout: 45, auth_type: 'oauth', url: 'https://example.com/sse',
      oauth: { scopes: [], client_id: 'client-1', client_secret: 'stored-secret' },
    },
  })
  const vm = dialog(t, {
    updateMcpService: async (_tid: string, _sid: string, input: unknown) => { updated = input; return stored },
  }, stored)
  vm.$.props.visible = true
  await vue.nextTick()
  await vm.save()
  assert.equal(updated.config.oauth.client_secret, 'stored-secret')
})
