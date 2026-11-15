import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'
function setup(t: Parameters<typeof fixture>[0]) {
  const f = fixture(t), api = f.evaluate(readFileSync(new URL('../../../../core/src/api/enterprise-parsers.ts', import.meta.url), 'utf8'), { '../utils/request': {} })
  const auth = reactive({ effectiveTenantId: 'a', currentTenantRole: 'owner', user: { id: 'u' } }), context = reactive({ ready: true, revision: 0 })
  const dialogs: { onConfirm: () => Promise<void>; hide: () => void }[] = [], writes: { tenant: string; config: Record<string, unknown> }[] = []
  let pendingWrite = false, finishWrite: ((value: Record<string, unknown>) => void) | undefined
  let failSave = false, failCatalog = false, finish: ((value: unknown) => void) | undefined
  const mounted = f.component(new URL('./ParserPage.vue', import.meta.url), {
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { DialogPlugin: { confirm: (options: object) => { const d = { ...options, hide() {} } as typeof dialogs[number]; dialogs.push(d); return d } } },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, '../../stores/context': { useAdminContext: () => context },
    '@nexus-web/core/api/enterprise-parsers': { ...api,
      getEnterpriseParserConfig: async (tenant: string) => tenant === 'a' ? { mineru_api_key: '******', mineru_endpoint: 'old', mineru_enable_table: false } : new Promise(resolve => { finish = resolve }),
      listEnterpriseParserEngines: async () => { if (failCatalog) throw Error('offline'); return [] },
      saveEnterpriseParserConfig: async (tenant: string, config: Record<string, unknown>) => { writes.push({ tenant, config: { ...config } }); if (failSave) throw Error('secret must not be displayed'); if (pendingWrite) return new Promise(resolve => { finishWrite = resolve }); return { ...config, mineru_api_key: '******' } },
    },
  })
  return { ...mounted, auth, context, writes, dialogs, deferWrite: () => { pendingWrite = true }, finishWrite: (value: Record<string, unknown>) => finishWrite?.(value), failSave: () => { failSave = true }, failCatalog: () => { failCatalog = true }, finish: (v: unknown) => finish?.(v) }
}
test('密钥不回显，保存前确认，保留原密钥和 false 并接收脱敏回执', async t => {
  const s = setup(t); await flush(); assert.equal(s.vm.draft.mineru_api_key, '')
  s.vm.draft.mineru_endpoint = 'new'; s.vm.save(); assert.equal(s.writes.length, 0)
  await s.dialogs[0].onConfirm(); assert.equal(s.writes[0].config.mineru_api_key, '******'); assert.equal(s.writes[0].config.mineru_enable_table, false)
  assert.equal(s.vm.dirty, false); assert.equal(s.vm.success, 'adminParsers.saved')
})
test('清除和轮换密钥互斥，失败保留普通草稿但清理一次性密钥', async t => {
  const s = setup(t); await flush(); s.failSave()
  s.vm.clearSecret('mineru_api_key', true); assert.equal(s.vm.payload.mineru_api_key, undefined)
  s.vm.secret('mineru_api_key', 'new-secret'); assert.equal(s.vm.cleared.length, 0)
  s.vm.draft.mineru_endpoint = 'new'; s.vm.save(); await s.dialogs[0].onConfirm()
  assert.equal(s.writes[0].config.mineru_api_key, 'new-secret'); assert.equal(s.vm.draft.mineru_api_key, '')
  assert.equal(s.vm.draft.mineru_endpoint, 'new'); assert.equal(s.vm.error, 'adminParsers.saveFailed')
})
test('保存成功后目录刷新失败独立呈现，不把已保存结果视为失败', async t => {
  const s = setup(t); await flush(); s.failCatalog(); s.vm.draft.mineru_endpoint = 'new'; s.vm.save(); await s.dialogs[0].onConfirm()
  assert.equal(s.vm.snapshot.mineru_endpoint, 'new'); assert.equal(s.vm.success, 'adminParsers.saved'); assert.equal(s.vm.error, 'adminParsers.refreshFailed')
})
test('切换企业作废旧确认和迟到读取，非管理角色不能加载或保存', async t => {
  const s = setup(t); await flush(); s.vm.draft.mineru_endpoint = 'new'; s.vm.save(); s.auth.effectiveTenantId = 'b'
  await s.dialogs[0].onConfirm(); assert.equal(s.writes.length, 0); assert.equal(s.vm.snapshot, null)
  s.auth.currentTenantRole = 'contributor'; s.finish({ mineru_endpoint: 'stale' }); await flush()
  assert.equal(s.vm.allowed, false); assert.equal(s.vm.snapshot, null); s.vm.save(); assert.equal(s.dialogs.length, 1)
})
test('账号、权限及卸载清空密钥和未提交草稿', async t => {
  const s = setup(t); await flush(); s.vm.secret('mineru_api_key', 'secret'); s.auth.user.id = 'other'
  assert.equal(s.vm.draft.mineru_api_key, undefined); await flush()
  s.vm.secret('mineru_api_key', 'secret'); s.context.ready = false; assert.equal(s.vm.snapshot, null)
  s.context.ready = true; await flush(); s.close(); assert.equal(s.vm.snapshot, null)
})

test('三态区分 false 和默认，提交时禁止重复写入，企业切换丢弃迟到回执', async t => {
  const s = setup(t); await flush()
  s.vm.flag('mineru_enable_table', 'default'); assert.equal(s.vm.payload.mineru_enable_table, undefined)
  s.vm.flag('mineru_enable_table', 'false'); assert.equal(s.vm.payload.mineru_enable_table, false)
  s.vm.draft.mineru_endpoint = 'new'; s.deferWrite(); s.vm.save()
  const pending = s.dialogs[0].onConfirm(); s.vm.save(); assert.equal(s.dialogs.length, 1); assert.equal(s.vm.busy, true)
  s.auth.effectiveTenantId = 'b'; s.finishWrite({ mineru_endpoint: 'stale' }); await pending
  assert.equal(s.vm.snapshot, null); assert.equal(s.vm.success, '')
})
