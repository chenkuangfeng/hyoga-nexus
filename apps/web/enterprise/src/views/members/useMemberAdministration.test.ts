import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

type Options = { permitted?: boolean; owner?: boolean; slowList?: boolean; partialFailure?: boolean; newTenantAfterRefresh?: string }
function setup(t: Parameters<typeof fixture>[0], options: Options = {}) {
  const f = fixture(t), calls: Array<{ operation: string; tenant: string; user?: string; input?: any }> = []
  const auth = vue.reactive({ effectiveTenantId: 'a', user: { id: 'actor' }, currentTenantRole: options.owner === false ? 'admin' : 'owner',
    refreshFromAuthMe: async () => { calls.push({ operation: 'auth', tenant: auth.effectiveTenantId }); context.permissions = []; if (options.newTenantAfterRefresh) auth.effectiveTenantId = options.newTenantAfterRefresh; return true }, logout() {} })
  const context = vue.reactive({ ready: true, revision: 0, permissions: options.permitted === false ? [] : ['members:manage'],
    can(permission: string) { return this.ready && this.permissions.includes(permission) },
    invalidate() { this.ready = false; this.revision++ }, load: async () => { calls.push({ operation: 'permissions', tenant: auth.effectiveTenantId }); context.ready = true },
  })
  const baseMembers = [{ tenant_id: 'a', user_id: options.owner === false ? 'tenant-owner' : 'actor', role: 'owner', status: 'active', joined_at: '2026-11-13', email: 'actor@example.com', username: 'actor', display_name: 'Owner' }, { tenant_id: 'a', user_id: 'other', role: 'contributor', status: 'active', joined_at: '2026-11-13', email: 'other@example.com', username: 'other', display_name: 'Other' }]
  const person = { kind: 'person', id: 'invite', user_id: 'invited', email: 'invited@example.com', display_name: 'Invited', role: 'viewer', status: 'pending', created_at: '2026-11-13' }
  const link = { kind: 'link', id: 'link', invite_path: '/join?token=secret', expires_at: '2026-11-20', accepted_count: 0, role: 'viewer', status: 'pending', created_at: '2026-11-13' }
  const dialogs: Array<{ onConfirm: () => Promise<void>; onClose: () => void; hide: () => void }> = []
  let finishList: (rows: unknown[]) => void = () => {}, finishMutation: (value: unknown) => void = () => {}, delayed = false
  const record = (operation: string, tenant: string, user?: string, input?: unknown) => calls.push({ operation, tenant, user, input })
  const api = {
    listEnterpriseMembers: (tenant: string) => { record('list', tenant); return options.slowList && tenant === 'a' ? new Promise(resolve => { finishList = resolve }) : Promise.resolve(baseMembers.map(row => ({ ...row, tenant_id: tenant }))) },
    listEnterpriseInvitations: async (tenant: string) => { record('invitations', tenant); if (options.partialFailure) throw new Error('invitation failure'); return [person, link] },
    changeEnterpriseMemberRole: (tenant: string, user: string, role: string) => { record('role', tenant, user, role); const row = { ...baseMembers.find(row => row.user_id === user), tenant_id: tenant, role }; return delayed ? new Promise(resolve => { finishMutation = resolve }) : Promise.resolve(row) },
    removeEnterpriseMember: async (tenant: string, user: string) => { record('remove', tenant, user) },
    revokeEnterpriseInvitation: async (tenant: string, id: string) => { record('revoke', tenant, id) },
    addEnterpriseMember: (tenant: string, input: object) => { record('add', tenant, undefined, { ...input }); return delayed ? new Promise(resolve => { finishMutation = resolve }) : Promise.resolve({ status: 'invited', invitation_id: 'new' }) },
    createEnterpriseInviteLink: async (tenant: string, role: string, days: number) => { record('link', tenant, undefined, { role, days }); return link },
  }
  const module = f.evaluate(readFileSync(new URL('./useMemberAdministration.ts', import.meta.url), 'utf8'), {
    vue, 'vue-router': { useRouter: () => ({ replace: async () => {} }) }, 'tdesign-vue-next': { DialogPlugin: { confirm: (options: { onConfirm: () => Promise<void>; onClose: () => void }) => { const dialog = { ...options, hide() {} }; dialogs.push(dialog); return dialog } } },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useEnterpriseContext: () => context }, '@nexus-web/core/api/enterprise-members': api,
  })
  const mounted = f.mount({ setup: () => module.useMemberAdministration((key: string) => key) })
  return { ...mounted, auth, context, calls, baseMembers, person, link, dialogs, delay: () => { delayed = true }, finishList: () => finishList(baseMembers), finish: (value: unknown) => finishMutation(value), mutations: () => calls.filter(row => ['role', 'remove', 'revoke', 'add', 'link'].includes(row.operation)) }
}

test('无成员管理权限不读取数据；部分邀请失败不丢弃成员列表', async t => {
  const s = setup(t, { permitted: false })
  await flush(); assert.equal(s.calls.length, 0)
  s.context.permissions = ['members:manage']; await flush()
  assert.equal(s.vm.members.length, 2)
  assert.equal(s.vm.invitations.length, 2)
})
test('邀请列表失败仍可查看成员；搜索与分页使用完整成员列表', async t => {
  const s = setup(t, { partialFailure: true })
  await flush()
  assert.equal(s.vm.membersReady, true); assert.equal(s.vm.invitationsReady, false)
  assert.notEqual(s.vm.invitationsError, '')
  s.vm.search = 'OTHER@EXAMPLE.COM'; await flush()
  assert.equal(s.vm.filteredMembers.length, 1)
  s.vm.search = 'does-not-exist'; assert.equal(s.vm.filteredMembers.length, 0)
})
test('最后一个 owner 不能被移除或降权；其他成员修改先确认', async t => {
  const s = setup(t); await flush()
  s.vm.remove(s.vm.members[0]); s.vm.changeRole(s.vm.members[0], 'viewer')
  assert.equal(s.dialogs.length, 0)
  s.vm.changeRole(s.vm.members[1], 'admin')
  assert.equal(s.mutations().length, 0)
  await s.dialogs[0].onConfirm()
  assert.equal(s.mutations()[0].operation, 'role')
  assert.equal(s.vm.members[1].role, 'admin')
})
test('非 owner 的成员管理员不能改 owner 或授予 owner，可管理其他基础角色', async t => {
  const s = setup(t, { owner: false }); await flush()
  s.vm.remove(s.vm.members[0]); s.vm.changeRole(s.vm.members[0], 'viewer'); s.vm.changeRole(s.vm.members[1], 'owner')
  assert.equal(s.dialogs.length, 0)
  s.vm.remove(s.vm.members[1]); await s.dialogs[0].onConfirm()
  assert.equal(s.vm.members.length, 1)
})
test('切换企业后旧请求和确认失效，退出清理邀请链接与临时密码', async t => {
  const s = setup(t, { slowList: true })
  s.auth.effectiveTenantId = 'b'; await flush()
  s.finishList(); await flush()
  assert.equal(s.vm.members[0].tenant_id, 'b')
  s.vm.revoke(s.vm.invitations[0]); s.auth.effectiveTenantId = 'c'; await flush()
  await s.dialogs[0].onConfirm(); assert.equal(s.mutations().length, 0)
  s.vm.openEditor(); s.vm.createAccount = true; s.vm.form.password = 'private-secret'
  s.close(); assert.equal(s.vm.form.password, ''); assert.equal(s.vm.invitations.length, 0)
})
test('密码提交前从表单清空，旧账号新增响应不在新身份下回显结果', async t => {
  const s = setup(t); await flush()
  s.vm.openEditor(); s.vm.createAccount = true
  s.vm.form.email = 'NEW@example.com'; s.vm.form.username = 'NEW'; s.vm.form.password = 'temporary-secret'
  s.delay(); const pending = s.vm.submitMember({ validateResult: true })
  assert.equal(s.vm.form.password, '')
  assert.equal(s.mutations()[0].input.password, 'temporary-secret')
  s.auth.user = { id: 'other-account' }; await flush()
  s.finish({ status: 'created', user_id: 'new' }); await pending
  assert.equal(s.vm.success, ''); assert.equal(s.vm.editorOpen, false)
})
test('自身降权后刷新身份与权限，及时撤掉成员管理入口', async t => {
  const s = setup(t); await flush()
  s.vm.members.push({ ...s.baseMembers[1], user_id: 'second-owner', role: 'owner' })
  s.vm.changeRole(s.vm.members[0], 'viewer'); await s.dialogs[0].onConfirm(); await flush()
  assert.equal(s.calls.some(row => row.operation === 'auth'), true)
  assert.equal(s.vm.canManage, false); assert.equal(s.vm.members.length, 0)
})
test('链接有效期按 1–30 天校验；权限撤销使旧确认失效', async t => {
  const s = setup(t); await flush()
  s.vm.openLink(); s.vm.linkForm.days = undefined; await s.vm.submitLink({ validateResult: true })
  assert.equal(s.mutations().length, 0)
  s.vm.linkForm.days = 7; await s.vm.submitLink({ validateResult: true })
  assert.equal(s.mutations()[0].operation, 'link'); assert.equal(s.vm.tab, 'invitations')
  s.vm.revoke(s.vm.invitations[0]); s.context.permissions = []; await s.dialogs[0].onConfirm()
  assert.equal(s.mutations().length, 1); assert.equal(s.vm.invitations.length, 0)
})


test('移除自身后默认企业变化，权限重新加载到新的当前企业', async t => {
  const s = setup(t, { newTenantAfterRefresh: 'b' }); await flush()
  s.vm.members.push({ ...s.baseMembers[1], user_id: 'second-owner', role: 'owner' })
  s.vm.remove(s.vm.members[0]); await s.dialogs[0].onConfirm(); await flush()
  assert.equal(s.auth.effectiveTenantId, 'b')
  assert.equal(s.calls.some(row => row.operation === 'permissions' && row.tenant === 'b'), true)
  assert.equal(s.vm.members.length, 0)
})


test('取消确认后，迟到的确认回调不会执行移除', async t => {
  const s = setup(t); await flush()
  s.vm.remove(s.vm.members[1]); s.dialogs[0].onClose(); await s.dialogs[0].onConfirm()
  assert.equal(s.mutations().length, 0)
})
