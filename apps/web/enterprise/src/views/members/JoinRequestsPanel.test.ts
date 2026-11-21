import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive, ref } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

type Options = { applicationFailure?: boolean; permissions?: string[]; departmentFailure?: boolean; departments?: Array<{ id: string; name: string; status: string; parent_id: string | null }>; slowList?: boolean }
function setup(t: Parameters<typeof fixture>[0], options: Options = {}) {
  const auth = reactive({ effectiveTenantId: 'a', user: { id: 'actor' } })
  const context = reactive({ ready: true, revision: 0, permissions: options.permissions || ['members:manage', 'org:manage'], can(permission: string) { return this.ready && this.permissions.includes(permission) } })
  const calls: Array<{ operation: string; tenant: string; id?: string; input?: any; user?: string }> = [], events: string[] = []
  const application = { id: 'request', user_id: 'person', email: 'person@example.com', display_name: 'Person', role: 'contributor', status: 'pending', unit_id: null, message: '申请加入', created_at: '2026-11-13' }
  const departments = options.departments || [{ id: 'root', name: '公司', status: 'active', parent_id: null }, { id: 'unit', name: '研发', status: 'active', parent_id: 'root' }, { id: 'disabled', name: '停用部门', status: 'disabled', parent_id: 'root' }]
  let finishList: (rows: unknown[]) => void = () => {}, finishAction: () => void = () => {}, delayed = false, failAction = false, failList = options.applicationFailure === true
  const record = (operation: string, tenant: string, id?: string, input?: unknown, user?: string) => calls.push({ operation, tenant, id, input, user })
  const mounted = fixture(t).component(new URL('./JoinRequestsPanel.vue', import.meta.url), {
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useEnterpriseContext: () => context },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key, locale: ref('zh-CN') }) },
    '@nexus-web/core/api/enterprise-members': {
      listEnterpriseApplications: (tenant: string) => { record('list', tenant); if (failList) return Promise.reject(new Error('list failure')); return options.slowList && tenant === 'a' ? new Promise(resolve => { finishList = resolve }) : Promise.resolve([{ ...application, id: `request-${tenant}` }]) },
      approveEnterpriseApplication: async (tenant: string, id: string, input: unknown, user: string) => { record('approve', tenant, id, input, user); if (failAction) throw new Error('conflict'); if (delayed) await new Promise<void>(resolve => { finishAction = resolve }) },
      rejectEnterpriseApplication: async (tenant: string, id: string, reason: string) => { record('reject', tenant, id, reason); if (failAction) throw new Error('conflict'); if (delayed) await new Promise<void>(resolve => { finishAction = resolve }) },
    },
    '@nexus-web/core/api/enterprise-admin': { listPolicyDepartments: async (tenant: string) => { record('departments', tenant); if (options.departmentFailure) throw new Error('department failure'); return departments } },
  }, { onApproved: () => events.push('approved'), onBusy: (value: boolean) => events.push(`busy:${value}`) })
  return { ...mounted, auth, context, calls, events, application, departments, recover: () => { failList = false }, delay: () => { delayed = true }, fail: () => { failAction = true }, finish: () => finishAction(), finishList: () => finishList([application]), actions: () => calls.filter(row => ['approve', 'reject'].includes(row.operation)) }
}

test('无成员权限不发请求；没有组织权限时拒绝仍可用，批准不可用', async t => {
  const s = setup(t, { permissions: [] }); await flush()
  assert.equal(s.calls.length, 0)
  s.context.permissions = ['members:manage']; await flush()
  assert.equal(s.calls.some(row => row.operation === 'departments'), false)
  assert.equal(s.vm.canApprove, false)
  s.vm.open('approve', s.vm.applications[0]); assert.equal(s.vm.mode, '')
  s.vm.open('reject', s.vm.applications[0]); s.vm.form.reason = '不符合要求'
  await s.vm.submit({ validateResult: true })
  assert.equal(s.actions()[0].operation, 'reject')
})
test('部门名保留路径；只有启用且来自当前列表的部门可批准', async t => {
  const s = setup(t); await flush()
  assert.equal(s.vm.departmentOptions.find((row: { value: string }) => row.value === 'unit').label, '公司 / 研发')
  s.vm.open('approve', s.vm.applications[0])
  for (const id of ['', 'unknown', 'disabled']) { s.vm.form.unit_id = id; await s.vm.submit({ validateResult: true }) }
  assert.equal(s.actions().length, 0)
  s.vm.form.unit_id = 'unit'; s.vm.form.role = 'viewer'
  await s.vm.submit({ validateResult: true })
  assert.deepEqual(JSON.parse(JSON.stringify(s.actions()[0])), { operation: 'approve', tenant: 'a', id: 'request-a', input: { unit_id: 'unit', role: 'viewer' }, user: 'person' })
  assert.equal(s.vm.applications.length, 0); assert.equal(s.vm.mode, '')
  assert.equal(s.events.includes('approved'), true)
})
test('部门加载失败不丢申请，不自动选择部门，拒绝原因必须非空且不超过 500 字符', async t => {
  const s = setup(t, { departmentFailure: true }); await flush()
  assert.equal(s.vm.ready, true); assert.equal(s.vm.canApprove, false); assert.equal(s.vm.applications.length, 1)
  assert.notEqual(s.vm.departmentError, '')
  s.vm.open('reject', s.vm.applications[0])
  for (const reason of ['  ', 'x'.repeat(501)]) { s.vm.form.reason = reason; await s.vm.submit({ validateResult: true }) }
  assert.equal(s.actions().length, 0)
  s.vm.form.reason = '  条件不符  '; await s.vm.submit({ validateResult: true })
  assert.equal(s.actions()[0].input, '条件不符'); assert.equal(s.events.includes('approved'), false)
})
test('取消后旧提交不能操作；服务端冲突时保留表单和申请并显示错误', async t => {
  const s = setup(t); await flush()
  s.vm.open('reject', s.vm.applications[0]); s.vm.form.reason = '条件不符'; s.vm.closeDialog()
  await s.vm.submit({ validateResult: true }); assert.equal(s.actions().length, 0)
  s.vm.open('reject', s.vm.applications[0]); s.vm.form.reason = '条件不符'; s.fail()
  await s.vm.submit({ validateResult: true })
  assert.equal(s.vm.applications.length, 1); assert.equal(s.vm.mode, 'reject'); assert.notEqual(s.vm.error, '')
})
test('旧企业列表和审批回执不能覆盖新作用域；提交中不重复发送', async t => {
  const s = setup(t, { slowList: true })
  s.auth.effectiveTenantId = 'b'; await flush(); s.finishList(); await flush()
  assert.equal(s.vm.applications[0].id, 'request-b')
  s.vm.open('approve', s.vm.applications[0]); s.vm.form.unit_id = 'unit'; s.delay()
  const pending = s.vm.submit({ validateResult: true })
  await s.vm.submit({ validateResult: true }); assert.equal(s.actions().length, 1)
  s.auth.effectiveTenantId = 'c'; await flush(); s.finish(); await pending
  assert.equal(s.vm.applications[0].id, 'request-c'); assert.equal(s.vm.success, '')
  assert.equal(s.events.includes('approved'), false)
})
test('账号、权限和刷新变化清空审批表单；卸载不再发送成员刷新事件', async t => {
  const s = setup(t); await flush()
  s.vm.open('reject', s.vm.applications[0]); s.vm.form.reason = 'private reason'
  s.auth.user = { id: 'new-actor' }; assert.equal(s.vm.target, null); assert.equal(s.vm.form.reason, '')
  await flush(); s.vm.open('reject', s.vm.applications[0]); s.vm.form.reason = 'refresh reason'
  s.vm.$.props.refreshKey++; assert.equal(s.vm.target, null); assert.equal(s.vm.form.reason, '')
  await flush(); s.vm.open('approve', s.vm.applications[0]); s.vm.form.unit_id = 'unit'; s.delay()
  const pending = s.vm.submit({ validateResult: true }); s.close(); s.finish(); await pending
  assert.equal(s.events.includes('approved'), false); assert.equal(s.vm.applications.length, 0)
  assert.equal(s.events.at(-1), 'busy:false')
})
test('失去组织权限使批准表单失效；失去成员权限清空列表', async t => {
  const s = setup(t); await flush()
  s.vm.open('approve', s.vm.applications[0]); s.vm.form.unit_id = 'unit'
  s.context.permissions = ['members:manage']; assert.equal(s.vm.mode, ''); await flush()
  assert.equal(s.vm.canApprove, false)
  s.context.permissions = []; assert.equal(s.vm.applications.length, 0)
  await s.vm.submit({ validateResult: true }); assert.equal(s.actions().length, 0)
})


test('无启用部门时不批准，伪造 owner 角色不能提交', async t => {
  const s = setup(t, { departments: [{ id: 'unit', name: '停用部门', status: 'disabled', parent_id: null }] }); await flush()
  assert.equal(s.vm.canApprove, false)
  s.vm.open('approve', s.vm.applications[0]); assert.equal(s.vm.mode, '')
  s.vm.departments[0].status = 'active'; s.vm.open('approve', s.vm.applications[0])
  s.vm.form.unit_id = 'unit'; s.vm.form.role = 'owner'; await s.vm.submit({ validateResult: true })
  assert.equal(s.actions().length, 0)
})


test('申请加载失败不可审批，重试后恢复，不把错误当成空列表成功', async t => {
  const s = setup(t, { applicationFailure: true }); await flush()
  assert.equal(s.vm.ready, false); assert.notEqual(s.vm.error, '')
  s.vm.open('approve', s.application); s.vm.open('reject', s.application)
  assert.equal(s.vm.mode, ''); assert.equal(s.actions().length, 0)
  s.recover(); await s.vm.load()
  assert.equal(s.vm.ready, true); assert.equal(s.vm.applications.length, 1); assert.equal(s.vm.error, '')
})
