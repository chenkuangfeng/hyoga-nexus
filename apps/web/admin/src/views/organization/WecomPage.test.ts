import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0]) {
  const f = fixture(t), auth = vue.reactive({ effectiveTenantId: 'a', user: { id: 'u' } })
  const context = vue.reactive({ revision: 0, allowed: true, can: () => context.allowed })
  const calls: string[] = []
  let status = 'requested', deferred = false, finish: (value: unknown) => void = () => {}
  const config = () => ({ configured: true, corp_id: auth.effectiveTenantId, sync_status: status, apps: [] })
  const mounted = f.component(new URL('./WecomPage.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { MessagePlugin: { success() {}, error() {} } },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useAdminContext: () => context },
    '@nexus-web/core/utils/clipboard': { copyToClipboard: async () => true },
    '@nexus-web/core/api/enterprise-wecom': {
      getEnterpriseWecom: async (tenant: string) => { calls.push(tenant); return deferred ? new Promise(resolve => { finish = resolve }) : config() },
      requestEnterpriseWecomSync: async () => {}, saveEnterpriseWecom: async () => config(),
    },
  })
  return { ...mounted, auth, context, calls, complete: () => { status = 'ok' }, defer: () => { deferred = true }, finish: (value: unknown) => finish(value) }
}

test('排队时轮询状态，完成后停止且不清空凭据草稿', async t => {
  const s = setup(t); await flush(); s.vm.callbackToken = 'draft'
  s.complete(); t.mock.timers.tick(5000); await flush()
  assert.equal(s.vm.config.sync_status, 'ok'); assert.equal(s.vm.callbackToken, 'draft')
  const count = s.calls.length; t.mock.timers.tick(60000); await flush(); assert.equal(s.calls.length, count)
})
test('账号变化与卸载使正在等待的轮询失效', async t => {
  const s = setup(t); await flush(); s.defer(); t.mock.timers.tick(5000); await flush()
  s.context.allowed = false; await flush(); s.finish({ configured: true, corp_id: 'old', sync_status: 'ok' }); await flush()
  assert.equal(s.vm.config, null)
  s.close(); const count = s.calls.length; t.mock.timers.tick(60000); await flush(); assert.equal(s.calls.length, count)
})
test('持续排队时最多轮询12次，仍显示排队状态', async t => {
  const s = setup(t); await flush()
  for (let i = 0; i < 14; i++) { t.mock.timers.tick(5000); await flush() }
  assert.equal(s.calls.length, 13); assert.equal(s.vm.config.sync_status, 'requested')
})
