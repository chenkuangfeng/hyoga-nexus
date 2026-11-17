import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
import type { EnterpriseUsageLimit, EnterpriseUsageRow, UsageGroup } from '@nexus-web/core/api/enterprise-usage'

type Dialog = { body: string; onConfirm: () => Promise<void>; hide: () => void }
const reportRow = (key: string): EnterpriseUsageRow => ({ key, runs: 2, input_tokens: 10, output_tokens: 20, cache_read_tokens: 100, cache_creation_tokens: 50 })
function setup(t: Parameters<typeof fixture>[0], permissions = ['models:manage', 'members:manage', 'org:manage']) {
  const f = fixture(t)
  const auth = reactive({ effectiveTenantId: 'a', user: { id: 'owner' } })
  const context = reactive({ revision: 0, permissions, can(permission: string) { return this.permissions.includes(permission) } })
  const dialogs: Dialog[] = [], writes: unknown[][] = [], reads: unknown[][] = [], messages: string[] = []
  const limits: EnterpriseUsageLimit[] = [{ id: 'l1', scope_kind: 'tenant', scope_id: 'a', monthly_tokens: 1000, used_this_month: 30 }]
  const controls = {
    report: async (_tenant: string, _group: UsageGroup): Promise<EnterpriseUsageRow[]> => [reportRow('2026-11-01')],
    limits: async () => limits,
    members: async () => [{ user_id: 'u1', username: 'alice', display_name: 'Alice', email: 'alice@example.test' }],
    units: async () => [{ id: 'd1', name: 'Research' }],
    save: async () => {},
  }
  const mounted = f.component(new URL('./UsagePage.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string, params?: object) => key + (params ? ':' + JSON.stringify(params) : '') }) },
    'tdesign-vue-next': { DialogPlugin: { confirm: (options: object) => { const dialog = { ...options, hide() {} } as Dialog; dialogs.push(dialog); return dialog } }, MessagePlugin: { success: (message: string) => messages.push(message) } },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useAdminContext: () => context },
    '@nexus-web/core/api/enterprise-usage': {
      getEnterpriseUsage: async (tenant: string, group: UsageGroup, start: string, end: string) => { reads.push([tenant, group, start, end]); return controls.report(tenant, group) },
      listEnterpriseUsageLimits: async () => controls.limits(),
      saveEnterpriseUsageLimit: async (...args: unknown[]) => { writes.push(args); await controls.save() },
    },
    '@nexus-web/core/api/enterprise-members': { listEnterpriseMembers: async () => controls.members() },
    '@nexus-web/core/api/enterprise-organizations': { listOrganizationUnits: async () => controls.units() },
  })
  return { ...mounted, auth, context, controls, dialogs, writes, reads, messages, limits }
}

test('保存绑定确认的范围与数值，并阻止重复确认和重复提交', async t => {
  const s = setup(t); await flush()
  assert.equal(s.vm.totalInput + s.vm.totalOutput, 30) // 缓存用量只报告，不计入合计。
  s.vm.scopeChoice = 'org_unit:d1'; s.vm.limitValue = 500
  s.vm.addLimit(); s.vm.addLimit(); s.vm.removeLimit(s.vm.limits[0])
  assert.equal(s.dialogs.length, 1); assert.match(s.dialogs[0]!.body, /Research/)
  s.vm.scopeChoice = 'user:u1'; s.vm.limitValue = 999
  const pending = s.dialogs[0]!.onConfirm(); await s.dialogs[0]!.onConfirm(); await pending
  assert.deepEqual(s.writes, [['a', 'org_unit', 'd1', 500]])
  assert.deepEqual(s.messages, ['adminUsage.saved'])
})

test('伪造目录目标、无效数值和无权限状态均不可打开确认', async t => {
  const s = setup(t); await flush()
  s.vm.limitValue = 10; s.vm.scopeChoice = 'user:unknown'; s.vm.addLimit()
  s.vm.scopeChoice = 'tenant'
  for (const value of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, undefined]) { s.vm.limitValue = value; s.vm.addLimit() }
  assert.equal(s.dialogs.length, 0)
  const count = s.reads.length; s.context.permissions = []; await flush(); s.vm.limitValue = 10; s.vm.addLimit()
  assert.equal(s.reads.length, count); assert.equal(s.dialogs.length, 0)
})

test('企业、账号、权限代次或目录授权变化使旧确认失效', async t => {
  for (const [index, change] of [
    (s: ReturnType<typeof setup>) => { s.auth.effectiveTenantId = 'b' },
    (s: ReturnType<typeof setup>) => { s.auth.user.id = 'other' },
    (s: ReturnType<typeof setup>) => { s.context.revision++ },
    (s: ReturnType<typeof setup>) => { s.context.permissions = ['models:manage'] },
    (s: ReturnType<typeof setup>) => { s.context.permissions = [] },
  ].entries()) {
    await t.test(`作用域变化 ${index + 1}`, async child => {
      const s = setup(child); await flush()
      s.vm.scopeChoice = 'user:u1'; s.vm.limitValue = 200; s.vm.addLimit()
      change(s); await s.dialogs[0]!.onConfirm(); await flush()
      assert.equal(s.writes.length, 0); assert.equal(s.vm.scopeChoice, 'tenant')
    })
  }
})

test('尚未查询的分组草稿不改变已显示报表的行名', async t => {
  const s = setup(t); await flush()
  s.controls.report = async () => [reportRow('u1')]
  s.vm.groupBy = 'user'; await s.vm.load()
  assert.equal(s.vm.rowKey('u1'), 'Alice')
  s.vm.groupBy = 'org_unit'
  assert.equal(s.vm.rowKey('u1'), 'Alice'); assert.equal(s.vm.reportGroup, 'user')
  s.context.permissions = ['models:manage']; await flush()
  assert.equal(s.vm.groupBy, 'day'); assert.equal(s.reads.at(-1)![1], 'day')
})

test('晚到的旧查询不能覆盖新结果；卸载后也不能恢复数据', async t => {
  const s = setup(t); await flush()
  const finishes: ((rows: EnterpriseUsageRow[]) => void)[] = []
  s.controls.report = () => new Promise(resolve => finishes.push(resolve))
  const old = s.vm.load(), latest = s.vm.load()
  finishes[1]!([reportRow('latest')]); await latest
  finishes[0]!([reportRow('old')]); await old
  assert.equal(s.vm.rows[0].key, 'latest')
  const leaving = s.vm.load(); s.close(); finishes[2]!([reportRow('late')]); await leaving
  assert.equal(s.vm.ready, false); assert.equal(s.vm.rows.length, 0)
})

test('可选目录失败明确反馈，不阻断企业报表；刷新后可以恢复', async t => {
  const s = setup(t); await flush()
  const members = s.controls.members
  s.controls.members = async () => { throw Error('offline') }
  await s.vm.load()
  assert.equal(s.vm.ready, true); assert.equal(s.vm.error, '')
  assert.equal(s.vm.directoryErrors.length, 1); assert.match(s.vm.directoryErrors[0], /adminUsage.member/)
  assert.deepEqual(Array.from(s.vm.scopeOptions, (row: { value: string }) => row.value), ['tenant', 'org_unit:d1'])
  s.controls.members = members; await s.vm.load()
  assert.equal(s.vm.directoryErrors.length, 0); assert.equal(s.vm.scopeOptions.length, 3)
})

test('写入失败保留草稿和服务端列表，允许重新确认', async t => {
  const s = setup(t); await flush()
  s.controls.save = async () => { throw Error('offline') }
  s.vm.limitValue = 300; s.vm.addLimit(); await s.dialogs[0]!.onConfirm()
  assert.equal(s.vm.limitValue, 300); assert.equal(s.vm.limits[0].monthly_tokens, 1000)
  assert.equal(s.vm.saving, false); assert.equal(s.vm.error, 'adminUsage.saveFailed')
  s.controls.save = async () => {}; s.vm.addLimit(); await s.dialogs[1]!.onConfirm()
  assert.equal(s.writes.length, 2); assert.equal(s.vm.error, '')
})

test('移除也绑定原范围，晚到的保存回执不能在新企业反馈成功', async t => {
  const s = setup(t); await flush()
  s.vm.removeLimit(s.vm.limits[0]); await s.dialogs[0]!.onConfirm()
  assert.deepEqual(s.writes, [['a', 'tenant', null, null]])
  let finish!: () => void
  s.controls.save = () => new Promise(resolve => { finish = resolve })
  s.vm.limitValue = 300; s.vm.addLimit()
  const pending = s.dialogs[1]!.onConfirm(); s.auth.effectiveTenantId = 'b'; await flush(); finish(); await pending
  assert.deepEqual(s.messages, ['adminUsage.removed']); assert.equal(s.vm.scopeChoice, 'tenant')
})

test('无效自然日和倒置日期不查询服务端', async t => {
  const s = setup(t); await flush(); const count = s.reads.length
  s.vm.start = '2026-02-30'; await s.vm.load()
  assert.equal(s.vm.error, 'adminUsage.invalidDates')
  s.vm.start = '2026-11-20'; s.vm.end = '2026-11-01'; await s.vm.load()
  assert.equal(s.reads.length, count)
})
