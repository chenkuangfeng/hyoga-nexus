import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { reactive, nextTick } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0]) {
  const f = fixture(t), warnings: string[] = [], calls: string[] = []
  const auth = reactive({ effectiveTenantId: 'a', user: { id: 'u' } })
  const route = reactive({ query: {} as Record<string, string> })
  const drafts = reactive({ pageDraft: null as any, takePageDraft(kind: string) { if (this.pageDraft?.kind !== kind) return null; const draft = this.pageDraft.draft; this.pageDraft = null; return draft } })
  const helpers = f.evaluate(readFileSync(new URL('../../../../core/src/utils/nexusModelCards.ts', import.meta.url), 'utf8'), {})
  const view = { providers: [{ id: 'provider', scope: 'personal', name: 'Provider', base_url: 'https://example.test/v1', models: [{ id: 'profile', name: 'Model', model_type: 'chat', version_id: 'v1', options: {} }] }], defaults: {}, can_manage_tenant: false }
  const reads: Array<(value: unknown) => void> = []
  let slow = false, slowCreate = false, finishCreate: (value: unknown) => void = () => {}, failAdd = false
  const api = {
    getModelSettings: async (tenant: string) => { calls.push(`read:${tenant}`); return slow ? new Promise(resolve => { reads.push(resolve) }) : view },
    createProvider: async (tenant: string) => { calls.push(`provider:${tenant}`); return slowCreate ? new Promise(resolve => { finishCreate = resolve }) : { id: 'new-provider' } },
    addModel: async (tenant: string) => { calls.push(`model:${tenant}`); if (failAdd) throw new Error('failed'); return {} },
    editModel: async () => {}, updateProvider: async () => {}, testDraftConnection: async () => ({ ok: true, message: 'ok' }),
  }
  const deps = { 'tdesign-icons-vue-next/esm/components/add.js': { default: {} }, 'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) }, 'tdesign-vue-next': { MessagePlugin: { warning: (key: string) => warnings.push(key), error() {}, success() {} } },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth }, 'vue-router': { useRoute: () => route },
    '@/stores/pageDrafts': { usePageDraftStore: () => drafts }, './nexusModelCards': helpers,
    '@nexus-web/core/api/nexus-models': api,
  }
  const page = f.component(new URL('./NexusModelSettings.vue', import.meta.url), deps)
  return { ...page, auth, route, drafts, warnings, calls, view,
    slowRead: () => { slow = true }, finishRead: (value: unknown) => reads.shift()!(value),
    dialog: (props: Record<string, unknown> = {}) => f.component(new URL('./NexusModelEditorDialog.vue', import.meta.url), deps,
      { visible: true, tenantId: 'a', settings: view, editing: null, initialType: 'chat', ...props }),
    slowCreate: () => { slowCreate = true }, finishCreate: (value: unknown) => finishCreate(value), failAdd: (value: boolean) => { failAdd = value },
  }
}

test('聊天草稿一次消费并打开当前模型表单，local 不连接旧 Ollama', async t => {
  const s = setup(t); await flush()
  s.drafts.pageDraft = { kind: 'model', draft: { type: 'chat', model_name: 'tool-model', base_url: 'https://example.test' } }; await flush()
  assert.equal(s.vm.dialogVisible, true); assert.equal(s.vm.modelDraft.model_name, 'tool-model'); assert.equal(s.drafts.pageDraft, null)
  s.vm.dialogVisible = false
  s.drafts.pageDraft = { kind: 'model', draft: { type: 'chat', source: 'local' } }; await flush()
  assert.equal(s.vm.dialogVisible, false); assert.deepEqual(s.warnings, ['nexusModels.localDraftUnsupported'])
})
test('model_id 深链接只打开可管理的真实档案，旧企业目录响应不能污染新企业', async t => {
  const s = setup(t); await flush(); s.route.query.model_id = 'profile'; await flush()
  assert.equal(s.vm.editing.model.id, 'profile'); assert.equal(s.vm.dialogVisible, true)
  s.slowRead(); const pending = s.vm.reload(); s.auth.effectiveTenantId = 'b'; await flush()
  assert.equal(s.vm.settings, null); assert.equal(s.vm.dialogVisible, false)
  s.finishRead(s.view); await pending; assert.equal(s.vm.settings, null)
  s.finishRead({ ...s.view, providers: [] }); await flush(); assert.equal(s.vm.settings.providers.length, 0)
  s.close(); await nextTick()
})
test('模型草稿映射 vision/speech，只填白名单，不带入凭据或企业作用域', async t => {
  const s = setup(t); await flush()
  for (const [type, expected] of [['vllm', 'vision'], ['asr', 'speech']]) {
    const d = s.dialog({ draft: { type, model_name: 'name', base_url: 'https://example.test', provider: 'Provider', api_key: 'untrusted', scope: 'tenant' } })
    assert.equal(d.vm.form.model_type, expected); assert.equal(d.vm.form.model_name, 'name')
    assert.equal(d.vm.form.api_key, ''); assert.equal(d.vm.form.scope, 'personal'); d.close()
  }
})
test('保存中不重复创建，关闭后旧供应商结果不能继续创建模型', async t => {
  const s = setup(t); await flush(); const d = s.dialog()
  Object.assign(d.vm.form, { model_name: 'model', provider_name: 'Provider', base_url: 'https://example.test', api_key: 'secret' })
  s.slowCreate(); const pending = d.vm.save(); await d.vm.save()
  assert.equal(s.calls.filter(x => x.startsWith('provider:')).length, 1)
  d.close(); s.finishCreate({ id: 'old-provider' }); await pending
  assert.equal(s.calls.filter(x => x.startsWith('model:')).length, 0); assert.equal(d.vm.form.api_key, '')
})
test('供应商已创建而模型写入失败时，重试复用同一个供应商', async t => {
  const s = setup(t); await flush(); const d = s.dialog()
  Object.assign(d.vm.form, { model_name: 'model', provider_name: 'Provider', base_url: 'https://example.test', api_key: 'secret' })
  s.failAdd(true); await d.vm.save(); assert.equal(d.vm.form.api_key, '')
  s.failAdd(false); await d.vm.save()
  assert.equal(s.calls.filter(x => x.startsWith('provider:')).length, 1)
  assert.equal(s.calls.filter(x => x.startsWith('model:')).length, 2)
})

test('企业模型缺少维护权时，深链接不能打开编辑器', async t => {
  const s = setup(t); await flush()
  s.vm.settings = { ...s.view, providers: [{ ...s.view.providers[0], scope: 'tenant' }] }
  s.route.query.model_id = 'profile'; await flush()
  assert.equal(s.vm.dialogVisible, false); assert.equal(s.vm.editing, null)
})
