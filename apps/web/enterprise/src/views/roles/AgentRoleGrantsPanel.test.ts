import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
function setup(t: Parameters<typeof fixture>[0], fail = false, readFail = false) {
  const auth = reactive({ effectiveTenantId: 'a', user: { id: 'u' } })
  const context = reactive({ revision: 0, can: () => true })
  const dialogs: Array<{ onConfirm: () => Promise<void>; hide: () => void }> = [], calls: unknown[] = []
  let refreshes = 0
  const s = fixture(t).component(new URL('./AgentRoleGrantsPanel.vue', import.meta.url), {
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useEnterpriseContext: () => context },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { DialogPlugin: { confirm: (input: { onConfirm: () => Promise<void> }) => { const dialog = { ...input, hide() {} }; dialogs.push(dialog); return dialog } } },
    '@nexus-web/core/api/enterprise-roles': {
      listRoleAgentChoices: async () => { if (readFail) throw new Error('offline'); return [{ id: 'agent', name: 'Agent' }] },
      listRoleAgentGrants: async () => [{ role_id: 'r', agent_id: 'agent', permission: 'view' }, { role_id: 'r', agent_id: 'missing', permission: 'run' }],
      setRoleAgentGrants: async (...input: unknown[]) => { calls.push(input); if (fail) throw new Error('forbidden') },
    },
  }, { roles: [{ id: 'r', name: 'Role' }], disabled: false, refreshPermissions: async () => { refreshes++ } })
  return { ...s, auth, context, calls, dialogs, refreshes: () => refreshes }
}
test('读取已有授权，仅变更后确认提交 view/run，未知资源有提示', async t => {
  const s = setup(t); await flush()
  assert.equal(s.vm.unresolved, 1)
  s.vm.selectedRole = 'r'; s.vm.selectedAgent = 'agent'
  assert.equal(s.vm.permissions[0], 'view'); assert.equal(s.vm.canSave, false)
  s.vm.permissions = ['view', 'run']; s.vm.save(); assert.equal(s.calls.length, 0)
  await s.dialogs[0].onConfirm()
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0])), ['a', 'r', 'agent', ['view', 'run']])
  assert.equal(s.refreshes(), 1)
})
test('空数组撤销当前角色，切换选择或企业后旧确认不能提交', async t => {
  const s = setup(t); await flush()
  s.vm.selectedRole = 'r'; s.vm.selectedAgent = 'agent'; s.vm.permissions = []; s.vm.save()
  s.vm.selectedAgent = ''; await s.dialogs[0].onConfirm(); assert.equal(s.calls.length, 0)
  s.vm.selectedAgent = 'agent'; s.vm.permissions = []; s.vm.save(); await s.dialogs[1].onConfirm()
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0])), ['a', 'r', 'agent', []])
  s.vm.selectedRole = 'r'; s.vm.selectedAgent = 'agent'; s.vm.permissions = []; s.vm.save()
  s.auth.effectiveTenantId = 'b'; await flush(); await s.dialogs[2].onConfirm(); assert.equal(s.calls.length, 1)
})
test('服务端拒绝保留草稿，禁止未知目标和维护权限值', async t => {
  const s = setup(t, true); await flush()
  s.vm.selectedRole = 'r'; s.vm.selectedAgent = 'agent'; s.vm.permissions = ['manage']; assert.equal(s.vm.canSave, false)
  s.vm.permissions = ['run']; s.vm.save(); await s.dialogs[0].onConfirm()
  assert.equal(s.vm.error, 'forbidden'); assert.equal(s.vm.permissions[0], 'run'); assert.equal(s.vm.busy, false)
  s.vm.selectedAgent = 'missing'; assert.equal(s.vm.canSave, false)
})


test('候选读取失败禁止写入，保留可重试的独立错误状态', async t => {
  const s = setup(t, false, true); await flush()
  assert.equal(s.vm.ready, false); assert.equal(s.vm.loading, false); assert.notEqual(s.vm.error, '')
  s.vm.selectedRole = 'r'; s.vm.selectedAgent = 'agent'; s.vm.permissions = ['view']; s.vm.save()
  assert.equal(s.calls.length, 0); assert.equal(s.dialogs.length, 0)
})
