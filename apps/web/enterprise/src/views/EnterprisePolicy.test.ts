import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
import type { EnterprisePolicy } from '@nexus-web/core/api/enterprise-admin'

function setup(t: Parameters<typeof fixture>[0], permissions = ['policy:manage']) {
  const f = fixture(t)
  const { policyChanges } = f.evaluate(readFileSync(new URL('../../../core/src/api/enterprise-admin.ts', import.meta.url), 'utf8'), { '../utils/request': {} })
  const auth = reactive({ effectiveTenantId: 'tenant', user: { id: 'user' } })
  const context = reactive({ ready: true, revision: 0, permissions, can(permission: string) { return this.ready && this.permissions.includes(permission) } })
  const row: EnterprisePolicy = { self_build_agents: 'org_units', self_build_org_unit_ids: ['department'], personal_models: false, external_sharing: false, personal_wecom_channels: 'review', personal_external_channels: true, retention_days: 7 }
  const calls: Array<{ tenant: string; input: Partial<EnterprisePolicy> }> = []
  let confirm: (() => Promise<void>) | undefined, departmentCalls = 0
  let finish: ((row: EnterprisePolicy) => void) | undefined
  let delayed = false
  const mounted = f.component(new URL('./EnterprisePolicy.vue', import.meta.url), {
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../stores/context': { useEnterpriseContext: () => context },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { DialogPlugin: { confirm: (options: { onConfirm: () => Promise<void> }) => { confirm = options.onConfirm; return { hide() {} } } } },
    '@nexus-web/core/api/enterprise-admin': {
      policyChanges,
      getEnterprisePolicy: async () => ({ ...row, self_build_org_unit_ids: [...row.self_build_org_unit_ids] }),
      listPolicyDepartments: async () => { departmentCalls++; return [] },
      updateEnterprisePolicy: (tenant: string, input: Partial<EnterprisePolicy>) => { calls.push({ tenant, input }); return delayed ? new Promise<EnterprisePolicy>(resolve => { finish = resolve }) : Promise.resolve({ ...row, ...input }) },
    },
  })
  return { ...mounted, auth, context, row, calls, confirm: () => confirm!(), departments: () => departmentCalls, delay: () => { delayed = true }, finish: () => finish!({ ...row, personal_models: true }) }
}

test('部门不可读时保留原范围，确认后只提交修改字段', async t => {
  const s = setup(t)
  await flush()
  assert.equal(s.departments(), 0)
  assert.equal(s.vm.canChooseDepartments, false)
  s.vm.form.personal_models = true
  s.vm.submit({ validateResult: true })
  assert.equal(s.calls.length, 0)
  await s.confirm()
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0])), { tenant: 'tenant', input: { personal_models: true } })
  assert.equal(s.vm.form.self_build_org_unit_ids[0], 'department')
  assert.equal(s.vm.saved, true)
})

test('关闭自动清理显式提交 null；无效天数不能进入确认', async t => {
  const s = setup(t)
  await flush()
  s.vm.autoPurge = false
  s.vm.submit({ validateResult: true }); await s.confirm()
  assert.equal(s.calls[0].input.retention_days, null)
  s.vm.autoPurge = true; s.vm.days = undefined
  s.vm.submit({ validateResult: true })
  assert.equal(s.vm.validDays, false)
  assert.equal(s.calls.length, 1)
})

test('无策略权限不可提交；切换企业后旧确认不能写入', async t => {
  const s = setup(t, [])
  await flush()
  s.vm.form.personal_models = true; s.vm.submit({ validateResult: true })
  assert.equal(s.calls.length, 0)
  s.context.permissions = ['policy:manage']
  s.vm.submit({ validateResult: true })
  s.auth.effectiveTenantId = 'other'
  assert.equal(s.vm.snapshot, null)
  await s.confirm(); await flush()
  assert.equal(s.calls.length, 0)
})

test('切换账号后，晚到的保存结果不能覆盖新表单；卸载作废确认', async t => {
  const s = setup(t)
  await flush()
  s.vm.form.personal_models = true; s.vm.submit({ validateResult: true }); s.delay()
  const pending = s.confirm()
  s.auth.user = { id: 'other' }
  await flush()
  s.finish(); await pending
  assert.equal(s.vm.saved, false)
  assert.equal(s.vm.form.personal_models, false)
  s.vm.form.personal_models = true; s.vm.submit({ validateResult: true }); s.close()
  await s.confirm()
  assert.equal(s.calls.length, 1)
})
