import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

type Options = { permissions?: string[]; treeFailure?: boolean; candidateFailure?: boolean; memberFailure?: boolean; slowMembers?: boolean; empty?: boolean; includeMembers?: boolean }
function setup(t: Parameters<typeof fixture>[0], options: Options = {}) {
  const f = fixture(t), auth = vue.reactive({ effectiveTenantId: 'a', user: { id: 'actor' } })
  const context = vue.reactive({ revision: 0, ready: true, permissions: options.permissions || ['org:manage', 'members:manage'], can(permission: string) { return this.ready && this.permissions.includes(permission) } })
  let nodes = options.empty ? [] : [
    { id: 'r', parent_id: null, name: '公司', status: 'active', source: 'manual', sync_managed: false, member_count: 0 },
    { id: 'd', parent_id: 'r', name: '研发', status: 'active', source: 'manual', sync_managed: false, member_count: 1 },
    { id: 'e', parent_id: 'd', name: '子部门', status: 'active', source: 'manual', sync_managed: false, member_count: 1 },
    { id: 'l', parent_id: 'r', name: '空部门', status: 'active', source: 'manual', sync_managed: false, member_count: 0 },
    { id: 'w', parent_id: 'r', name: '企微部门', status: 'active', source: 'wecom', sync_managed: true, member_count: 1 },
  ]
  const positions: Record<string, Array<{ user_id: string; display_name: string; is_primary: boolean }>> = { d: [{ user_id: 'p', display_name: '成员P', is_primary: true }], e: [{ user_id: 'p', display_name: '成员P', is_primary: false }], w: [{ user_id: 'sync', display_name: '同步成员', is_primary: true }] }
  const calls: Array<{ operation: string; tenant: string; unit?: string; user?: string; input?: any }> = []
  const dialogs: Array<{ onConfirm: () => Promise<void>; onClose: () => void; hide: () => void }> = []
  let finishMembers: (rows: unknown[]) => void = () => {}, finishAction: (value: unknown) => void = () => {}, delayed = false, failed = false
  const record = (operation: string, tenant: string, unit?: string, user?: string, input?: unknown) => calls.push({ operation, tenant, unit, user, input })
  const helpers = f.evaluate(readFileSync(new URL('./organizationTree.ts', import.meta.url), 'utf8'), {})
  const compiled = f.evaluate(readFileSync(new URL('./useOrganizationAdministration.ts', import.meta.url), 'utf8'), {
    vue, './organizationTree': helpers, '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useEnterpriseContext: () => context },
    'tdesign-vue-next': { DialogPlugin: { confirm: (options: { onConfirm: () => Promise<void>; onClose: () => void }) => { const dialog = { ...options, hide() {} }; dialogs.push(dialog); return dialog } } },
    '@nexus-web/core/api/enterprise-members': { listEnterpriseMembers: async (tenant: string) => { record('candidates', tenant); if (options.candidateFailure) throw new Error('failed'); return ['p', 'q', 'sync'].map(user_id => ({ tenant_id: tenant, user_id, role: 'contributor', status: 'active', display_name: user_id.toUpperCase(), username: user_id, email: `${user_id}@example.com` })) } },
    '@nexus-web/core/api/enterprise-organizations': {
      listOrganizationUnits: async (tenant: string) => { record('tree', tenant); if (options.treeFailure) throw new Error('failed'); return nodes.map(row => ({ ...row, member_count: (positions[row.id] || []).length })) },
      listOrganizationMembers: (tenant: string, unit: string) => { record('members', tenant, unit); if (options.memberFailure) return Promise.reject(new Error('member failure')); return options.slowMembers && unit === 'd' ? new Promise(resolve => { finishMembers = resolve }) : Promise.resolve((positions[unit] || []).map(row => ({ ...row, source: unit === 'w' ? 'wecom' : 'manual' }))) },
      createOrganizationUnit: async (tenant: string, input: { name: string; parent_id?: string }) => { record('create', tenant, undefined, undefined, { ...input }); const row = { id: nodes.length ? 'new' : 'r', name: input.name, parent_id: input.parent_id || null, source: 'manual', status: 'active', member_count: 0 }; nodes.push(row); return row },
      updateOrganizationUnit: async (tenant: string, unit: string, input: object) => { record('update', tenant, unit, undefined, { ...input }); if (failed) throw new Error('conflict'); if (delayed) return await new Promise(resolve => { finishAction = resolve }); const row = nodes.find(row => row.id === unit)!; Object.assign(row, input); return { ...row } },
      deleteOrganizationUnit: async (tenant: string, unit: string) => { record('delete', tenant, unit); if (failed) throw new Error('historical positions'); nodes = nodes.filter(row => row.id !== unit) },
      assignOrganizationMember: async (tenant: string, unit: string, user: string, primary: boolean) => { record('assign', tenant, unit, user, primary); if (failed) throw new Error('failed'); const hasPrimary = Object.values(positions).some(rows => rows.some(row => row.user_id === user && row.is_primary)); const makePrimary = primary || !hasPrimary; if (makePrimary) for (const rows of Object.values(positions)) for (const row of rows) if (row.user_id === user) row.is_primary = false; const found = (positions[unit] || []).find(row => row.user_id === user); if (found) found.is_primary = makePrimary; else (positions[unit] ||= []).push({ user_id: user, display_name: user, is_primary: makePrimary }); return { unit_id: unit, user_id: user, is_primary: makePrimary } },
      removeOrganizationMember: async (tenant: string, unit: string, user: string) => { record('unassign', tenant, unit, user); if (failed) throw new Error('choose primary first'); positions[unit] = (positions[unit] || []).filter(row => row.user_id !== user) },
    },
  })
  const mounted = f.mount({ setup: () => compiled.useOrganizationAdministration((key: string) => key, { includeMembers: options.includeMembers }) })
  return { ...mounted, auth, context, calls, dialogs, fail: () => { failed = true }, delay: () => { delayed = true }, finish: (value: unknown) => finishAction(value), finishMembers: () => finishMembers([{ user_id: 'old', display_name: 'old', is_primary: true }]), mutations: () => calls.filter(row => ['create', 'update', 'delete', 'assign', 'unassign'].includes(row.operation)) }
}

test('无组织权限不读数据，树加载失败不能当作空树创建根', async t => {
  const s = setup(t, { permissions: ['members:manage'], treeFailure: true }); await flush()
  assert.equal(s.calls.length, 0)
  s.context.permissions = ['members:manage', 'org:manage']; await flush()
  assert.equal(s.vm.treeReady, false); assert.notEqual(s.vm.error, '')
  s.vm.openCreate(null); assert.equal(s.vm.editorOpen, false)
})
test('空树才能创建根；根不能移动或删除，移动选项排除当前子树', async t => {
  const s = setup(t, { empty: true }); await flush()
  s.vm.openCreate(null); s.vm.form.name = '公司'; await s.vm.save({ validateResult: true }); await flush()
  assert.equal(s.mutations()[0].input.parent_id, undefined)
  s.vm.removeUnit(); assert.equal(s.vm.canDelete, false)
  s.vm.openCreate(null); assert.equal(s.vm.editorOpen, false)
  s.vm.openEdit(); s.vm.form.parent_id = 'arbitrary'; await s.vm.save({ validateResult: true })
  assert.equal(s.mutations().length, 1)
})
test('父节点不可为自身或子树；移动与取消有确认，改名不发送伪造父节点', async t => {
  const s = setup(t); await flush(); s.vm.selectUnit('d'); await flush()
  s.vm.openEdit(); assert.equal(s.vm.parentOptions.some((row: { value: string }) => ['d', 'e'].includes(row.value)), false)
  s.vm.form.parent_id = 'e'; await s.vm.save({ validateResult: true }); assert.equal(s.mutations().length, 0)
  s.vm.form.parent_id = 'l'; await s.vm.save({ validateResult: true }); assert.equal(s.mutations().length, 0)
  s.vm.closeEditor(); await s.dialogs[0].onConfirm(); assert.equal(s.mutations().length, 0)
  s.vm.openEdit(); s.vm.form.name = '新名称'; await s.vm.save({ validateResult: true }); await flush()
  assert.deepEqual(s.mutations()[0].input, { name: '新名称' })
})
test('企微来源节点与归属在本页只读，但可新建手工子部门', async t => {
  const s = setup(t); await flush(); s.vm.selectUnit('w'); await flush()
  s.vm.openEdit(); s.vm.toggleStatus(); s.vm.removeUnit(); s.vm.setPrimary(s.vm.members[0]); s.vm.removeMember(s.vm.members[0])
  assert.equal(s.vm.editorOpen, false); assert.equal(s.dialogs.length, 0); assert.equal(s.mutations().length, 0)
  s.vm.openCreate('w'); s.vm.form.name = '手工子部门'; await s.vm.save({ validateResult: true }); await flush()
  assert.equal(s.mutations()[0].operation, 'create'); assert.equal(s.mutations()[0].input.parent_id, 'w')
})
test('没有成员列表权限不读取候选，仍能维护已有手工归属', async t => {
  const s = setup(t, { permissions: ['org:manage'] }); await flush(); s.vm.selectUnit('e'); await flush()
  assert.equal(s.calls.some(row => row.operation === 'candidates'), false)
  assert.equal(s.vm.canAssign, false)
  s.vm.setPrimary(s.vm.members[0]); await s.dialogs[0].onConfirm(); await flush()
  assert.equal(s.mutations()[0].input, true); assert.equal(s.vm.members[0].is_primary, true)
})
test('只能从已读取的候选中分配，首次主部门标记采用服务端结果', async t => {
  const s = setup(t); await flush(); s.vm.selectUnit('d'); await flush()
  s.vm.assignment.user_id = 'p'; await s.vm.assign(); assert.equal(s.mutations().length, 0)
  s.vm.assignment.user_id = 'unknown'; await s.vm.assign(); assert.equal(s.mutations().length, 0)
  s.vm.assignment.user_id = 'q'; await s.vm.assign(); await flush()
  assert.equal(s.mutations()[0].input, false)
  assert.equal(s.vm.members.find((row: { user_id: string }) => row.user_id === 'q').is_primary, true)
})
test('快速切换部门时旧成员响应不覆盖当前节点，旧确认也不执行', async t => {
  const s = setup(t, { slowMembers: true }); await flush()
  s.vm.selectUnit('d'); s.vm.selectUnit('e'); await flush(); s.finishMembers(); await flush()
  assert.equal(s.vm.selectedId, 'e'); assert.equal(s.vm.members[0].user_id, 'p')
  s.vm.removeMember(s.vm.members[0]); s.vm.selectUnit('r'); await flush(); await s.dialogs[0].onConfirm()
  assert.equal(s.mutations().length, 0)
})
test('候选读取失败仍可看树；后端历史关联拒绝删除时不丢节点', async t => {
  const s = setup(t, { candidateFailure: true }); await flush(); s.vm.selectUnit('l'); await flush()
  assert.equal(s.vm.treeReady, true); assert.equal(s.vm.canAssign, false); assert.notEqual(s.vm.candidatesError, '')
  s.fail(); s.vm.removeUnit(); await s.dialogs[0].onConfirm()
  assert.equal(s.vm.selectedId, 'l'); assert.notEqual(s.vm.error, ''); assert.equal(s.vm.units.some((row: { id: string }) => row.id === 'l'), true)
})
test('切换身份清空旧表单，迟到的保存结果不触发新企业刷新', async t => {
  const s = setup(t); await flush(); s.vm.selectUnit('d'); await flush()
  s.vm.openEdit(); s.vm.form.name = 'old input'; s.delay()
  const pending = s.vm.save({ validateResult: true })
  s.auth.effectiveTenantId = 'b'; s.auth.user = { id: 'new-actor' }; await flush()
  const trees = s.calls.filter(row => row.operation === 'tree').length
  assert.equal(s.vm.editorOpen, false); assert.equal(s.vm.form.name, '')
  s.finish({ id: 'd' }); await pending
  assert.equal(s.calls.filter(row => row.operation === 'tree').length, trees); assert.equal(s.vm.success, '')
  s.close(); assert.equal(s.vm.units.length, 0)
})


test('失去组织权限使旧确认和已选数据失效', async t => {
  const s = setup(t); await flush()
  s.vm.toggleStatus(); s.context.permissions = ['members:manage']; await s.dialogs[0].onConfirm()
  assert.equal(s.vm.units.length, 0); assert.equal(s.vm.canManage, false); assert.equal(s.mutations().length, 0)
})
test('当前部门成员读取失败时，不把未知归属当作空部门来分配或删除', async t => {
  const s = setup(t, { memberFailure: true }); await flush(); s.vm.selectUnit('l'); await flush()
  assert.equal(s.vm.membersReady, false); assert.notEqual(s.vm.membersError, '')
  s.vm.assignment.user_id = 'p'; await s.vm.assign(); s.vm.removeUnit()
  assert.equal(s.vm.canAssign, false); assert.equal(s.vm.canDelete, false); assert.equal(s.mutations().length, 0)
})

test('映射企微顶级部门的手工根也由 sync_managed 保护', async t => {
  const s = setup(t); await flush()
  s.vm.units.find((row: { id: string }) => row.id === 'r').sync_managed = true
  s.vm.selectUnit('r'); await flush(); s.vm.openEdit(); s.vm.toggleStatus(); s.vm.removeUnit()
  assert.equal(s.vm.manual, false); assert.equal(s.vm.editorOpen, false); assert.equal(s.mutations().length, 0)
  s.vm.openCreate('r'); assert.equal(s.vm.editorOpen, true)
})
test('混合归属可撤销手工贡献，同步节点的主部门仍可维护', async t => {
  const s = setup(t); await flush(); s.vm.selectUnit('d'); await flush()
  const row = s.vm.members[0]; row.source = 'mixed'; s.vm.removeMember(row)
  await s.dialogs[0].onConfirm(); assert.equal(s.mutations()[0].operation, 'unassign')
  s.vm.selectUnit('w'); await flush()
  s.vm.members[0].is_primary = false; s.vm.setPrimary(s.vm.members[0]); await s.dialogs[1].onConfirm()
  assert.equal(s.mutations()[1].operation, 'assign')
})


test('企业组织页只读节点，编辑下级后保留父组织并限制删除', async t => {
  const s = setup(t, { includeMembers: false })
  await flush()
  assert.deepEqual(s.calls.map(call => call.operation), ['tree'])
  const node = (id: string) => s.vm.units.find((row: { id: string }) => row.id === id)
  assert.equal(s.vm.canDeleteUnit(node('d')), false)
  assert.equal(s.vm.canDeleteUnit(node('l')), true)
  s.vm.openEdit('l')
  s.vm.form.name = '新组织名'
  await s.vm.save({ validateResult: true })
  assert.equal(s.vm.selectedId, 'r')
  assert.equal(node('l').name, '新组织名')
  assert.equal(s.calls.some(call => ['members', 'candidates'].includes(call.operation)), false)
})
