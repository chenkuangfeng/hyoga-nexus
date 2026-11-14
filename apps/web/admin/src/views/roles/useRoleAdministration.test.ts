import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

const fixtures = new WeakMap<object, ReturnType<typeof fixture>>()
function setup(t: Parameters<typeof fixture>[0], options: { memberFailure?: boolean; coreFailure?: boolean; failWrite?: boolean; loseAccess?: boolean; noMembersPermission?: boolean; unmountOnReconcile?: boolean; departments?: boolean; departmentFailure?: boolean } = {}) {
  const f = fixtures.get(t) || fixture(t)
  fixtures.set(t, f)
  const calls: Array<{ operation: string; input?: unknown }> = []
  const dialogs: Array<{ onConfirm: () => Promise<void>; onClose: () => void; hide: () => void }> = []
  const auth = vue.reactive({ effectiveTenantId: 'a', user: { id: 'u' }, logout() {}, refreshFromAuthMe: async () => true })
  let unmount = () => {}, permissionLoads = 0
  const context = vue.reactive({ ready: true, revision: 0, failed: false, permissions: options.noMembersPermission ? ['roles:manage'] : ['roles:manage', 'members:manage'],
    can(key: string) { return this.ready && this.permissions.includes(key) }, invalidate() { this.ready = false; this.revision++; if (options.unmountOnReconcile) unmount() },
    async load() { permissionLoads++; if (options.loseAccess) this.permissions = []; this.ready = true },
  })
  if (options.departments) context.permissions.push('org:manage')
  const role = { id: 'r', tenant_id: 'a', name: 'Custom', builtin: false, menus: ['roles'], apis: ['roles:manage'] }
  const builtin = { ...role, id: 'builtin', builtin: true, name: 'Auditor' }
  const record = (operation: string, input?: unknown) => { calls.push({ operation, input }); if (options.failWrite) throw new Error('write_failed') }
  const compiled = f.evaluate(readFileSync(new URL('./useRoleAdministration.ts', import.meta.url), 'utf8'), {
    '../organization/organizationTree': { organizationRows: (rows: { id: string; name: string; status: string }[]) => rows.map(node => ({ node, path: `Company / ${node.name}` })) },
    '@nexus-web/core/api/enterprise-organizations': { listOrganizationUnits: async () => { if (options.departmentFailure) throw new Error('tree_failed'); return [{ id: 'd', name: 'Dept', status: 'active' }, { id: 'disabled', name: 'Dept', status: 'disabled' }] } },
    vue, '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useAdminContext: () => context },
    'vue-router': { useRouter: () => ({ replace: async () => {} }) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key, te: () => false }) },
    'tdesign-vue-next': { MessagePlugin: { success() {}, error() {} }, DialogPlugin: { confirm: (input: { onConfirm: () => Promise<void>; onClose: () => void }) => { const dialog = { ...input, hide() {} }; dialogs.push(dialog); return dialog } } },
    '@nexus-web/core/api/enterprise-members': { listEnterpriseMembers: async () => { if (options.memberFailure) throw new Error('member_failed'); return [{ user_id: 'u', role: 'viewer', display_name: 'User' }, { user_id: 'owner', role: 'owner', display_name: 'Owner' }] } },
    '@nexus-web/core/api/enterprise-roles': {
      assignDepartmentRole: async (_tenant: string, unit: string, role: string) => { record('department', { unit, role }); return { assigned: ['u'], skipped: ['v'] } },
      listEnterpriseRoles: async () => [{ ...role }, { ...builtin }],
      getRoleCatalog: async () => { if (options.coreFailure) throw new Error('failed'); return { menus: ['roles'], apis: ['roles:manage', 'models:manage'] } },
      getRoleActorPermissions: async () => ({ menus: ['roles'], apis: ['roles:manage'] }),
      listRoleAssignments: async () => [{ user_id: 'u', role_id: 'r' }],
      createEnterpriseRole: async (_tenant: string, input: unknown) => { record('create', input); return role },
      updateEnterpriseRole: async (_tenant: string, _id: string, input: unknown) => { record('update', input); return role },
      setMemberRoleAssignment: async (_tenant: string, user: string, role: string, assigned: boolean) => record('assign', { user, role, assigned }),
    },
  })
  const s = f.mount({ setup() { return compiled.useRoleAdministration() } })
  unmount = s.close
  return { ...s, auth, context, calls, dialogs, permissionLoads: () => permissionLoads }
}

test('目录读取失败阻止所有写入，成员读取失败不影响角色维护', async t => {
  const s = setup(t, { coreFailure: true }); await flush()
  assert.equal(s.vm.ready, false); s.vm.openEditor(); assert.equal(s.vm.editor, false)
  const other = setup(t, { memberFailure: true }); await flush()
  assert.equal(other.vm.ready, true); assert.equal(other.vm.membersReady, false)
  other.vm.openEditor(); assert.equal(other.vm.editor, true)
})

test('内置角色只读，超出自身权限不能提交，已有自定义角色不发送改名', async t => {
  const s = setup(t); await flush()
  s.vm.openEditor(s.vm.roles[1]); s.vm.save(); assert.equal(s.dialogs.length, 0)
  s.vm.closeEditor(); s.vm.openEditor(); s.vm.form.name = 'New'; s.vm.form.apis = ['models:manage']; s.vm.save(); assert.equal(s.dialogs.length, 0)
  s.vm.form.apis = ['roles:manage']; s.vm.save(); assert.equal(s.calls.length, 0)
  await s.dialogs[0].onConfirm(); await flush(); assert.equal(s.calls[0].operation, 'create')
  s.vm.openEditor(s.vm.roles[0]); s.vm.form.name = 'Ignored'; s.vm.save()
  await s.dialogs[1].onConfirm(); await flush()
  assert.equal(s.calls[1].operation, 'update'); assert.equal('name' in (s.calls[1].input as object), false)
})

test('成员分配排除 owner 和重复授权，无成员管理权限时禁止成员写入', async t => {
  const s = setup(t); await flush()
  assert.equal(s.vm.memberChoices.length, 1)
  s.vm.selectedMember = 'u'; s.vm.selectedRole = 'r'; s.vm.assign(); assert.equal(s.dialogs.length, 0)
  s.vm.selectedRole = 'builtin'; s.vm.assign(); await s.dialogs[0].onConfirm(); await flush()
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].input)), { user: 'u', role: 'builtin', assigned: true })
  const other = setup(t, { noMembersPermission: true }); await flush()
  assert.equal(other.vm.ready, true); other.vm.revoke('u', 'r'); assert.equal(other.dialogs.length, 0)
})

test('切换企业或关闭编辑使旧确认失效，撤销自身管理权后禁止继续写入', async t => {
  const s = setup(t); await flush(); s.vm.openEditor(); s.vm.form.name = 'Draft'; s.vm.save()
  s.vm.closeEditor(); await s.dialogs[0].onConfirm(); assert.equal(s.calls.length, 0)
  s.vm.openEditor(); s.vm.form.name = 'Draft'; s.vm.save()
  s.auth.effectiveTenantId = 'b'; await flush(); await s.dialogs[1].onConfirm(); assert.equal(s.calls.length, 0)
  const other = setup(t, { loseAccess: true }); await flush()
  other.vm.revoke('u', 'r'); await other.dialogs[0].onConfirm(); await flush()
  assert.equal(other.vm.canManage, false); assert.equal(other.vm.ready, false); assert.equal(other.calls.length, 1)
})

test('写入失败保留表单并解除提交锁，允许重试', async t => {
  const s = setup(t, { failWrite: true }); await flush()
  s.vm.openEditor(); s.vm.form.name = 'Draft'; s.vm.save(); await s.dialogs[0].onConfirm()
  assert.equal(s.vm.editor, true); assert.equal(s.vm.form.name, 'Draft'); assert.equal(s.vm.busy, false); assert.equal(s.vm.error, 'write_failed')
})


test('清空权限导致父外壳卸载页面后仍完成身份校准和权限重读', async t => {
  const s = setup(t, { unmountOnReconcile: true }); await flush()
  s.vm.openEditor(); s.vm.form.name = 'Created'; s.vm.save()
  await s.dialogs[0].onConfirm(); await flush()
  assert.equal(s.calls[0].operation, 'create')
  assert.equal(s.permissionLoads(), 1)
  assert.equal(s.context.ready, true)
})


test('部门分配需要组织权限和可读的启用部门，仅提交部门与角色且先确认', async t => {
  const s = setup(t, { departments: true }); await flush()
  assert.equal(s.vm.departmentsReady, true)
  assert.equal(s.vm.departmentChoices[0].label, 'Company / Dept')
  s.vm.selectedDepartment = 'disabled'; s.vm.departmentRole = 'r'; s.vm.assignDepartment()
  assert.equal(s.dialogs.length, 0)
  s.vm.selectedDepartment = 'd'; s.vm.assignDepartment()
  assert.equal(s.calls.length, 0)
  await s.dialogs[0].onConfirm(); await flush()
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0].input)), { unit: 'd', role: 'r' })
  assert.equal(s.permissionLoads(), 1)
})

test('组织读取失败或权限缺失不阻断角色维护；切换企业使部门确认失效', async t => {
  const s = setup(t, { departments: true, departmentFailure: true }); await flush()
  assert.equal(s.vm.ready, true); assert.equal(s.vm.departmentsReady, false); assert.equal(s.vm.departmentError, 'tree_failed')
  s.vm.selectedDepartment = 'd'; s.vm.departmentRole = 'r'; s.vm.assignDepartment(); assert.equal(s.dialogs.length, 0)
  const other = setup(t, { departments: true }); await flush()
  other.vm.selectedDepartment = 'd'; other.vm.departmentRole = 'r'; other.vm.assignDepartment()
  other.auth.effectiveTenantId = 'b'; await flush(); await other.dialogs[0].onConfirm()
  assert.equal(other.calls.length, 0)
  const denied = setup(t); await flush(); assert.equal(denied.vm.canManageDepartments, false)
})
