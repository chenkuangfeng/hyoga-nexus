import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '@nexus-web/core/test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0], failWrites = false) {
  const writes: unknown[] = [], deleted: string[] = [], paths: string[] = []
  const copies: string[] = []
  let copyResult: boolean | Promise<boolean> = true
  let loggedOut = false, resolveRead: ((value: unknown) => void) | undefined
  const row = { id: 'a', code: 'alpha_01', name: 'Alpha', description: 'Desc', role: 'owner', status: 'active', created_at: '2026-11-14' }
  const auth = reactive({ effectiveTenantId: 'a', currentTenantRole: 'owner', user: { id: 'u' }, memberships: [{ tenant_id: 'a', tenant_name: 'Alpha' }],
    setSelectedTenant(_id: string, _name: string) {}, setMemberships(value: { tenant_id: string; tenant_name: string }[]) { this.memberships = value }, logout() { loggedOut = true } })
  const context = reactive({ ready: true, revision: 0, invalidate() { this.ready = false; this.revision++ } })
  const s = fixture(t).component(new URL('./EnterpriseInfo.vue', import.meta.url), {
    '@nexus-web/core/utils/clipboard': { copyToClipboard: async (value: string) => { copies.push(value); return copyResult } },
    '@nexus-web/core/stores/auth': { useAuthStore: () => auth },
    '../stores/context': { useEnterpriseContext: () => context },
    'vue-router': { useRouter: () => ({ replace: async (path: string) => { paths.push(path) } }) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    '@nexus-web/core/api/enterprise-info': {
      getEnterpriseInfo: async (id: string) => id === 'a' ? { ...row } : new Promise(resolve => { resolveRead = resolve }),
      updateEnterpriseInfo: async (_id: string, input: unknown) => { writes.push(input); if (failWrites) throw new Error('offline'); return { ...row, ...(input as object) } },
      archiveEnterprise: async (id: string) => { deleted.push(id); if (failWrites) throw new Error('shared_space_conflict') },
    },
  })
  return { ...s, copies, setCopyResult: (value: boolean | Promise<boolean>) => { copyResult = value }, auth, context, writes, deleted, paths, loggedOut: () => loggedOut, resolveRead: (value: unknown) => resolveRead?.(value), row }
}

test('名称和描述仅提交变化字段，空描述明确清除，并更新当前企业名称', async t => {
  const s = setup(t); await flush()
  s.vm.description = '  '
  await s.vm.save()
  assert.deepEqual(JSON.parse(JSON.stringify(s.writes)), [{ description: '' }])
  assert.equal(s.vm.snapshot.description, '')
  s.vm.name = 'Beta'
  await s.vm.save()
  assert.equal(s.auth.memberships[0].tenant_name, 'Beta')
  assert.equal(s.vm.saved, true)
})

test('切换企业或失去 owner 后丢弃表单与删除确认，不接受迟到读取', async t => {
  const s = setup(t); await flush()
  s.vm.openDelete(); s.vm.confirmationName = 'Alpha'
  s.auth.effectiveTenantId = 'b'
  assert.equal(s.vm.snapshot, null)
  assert.equal(s.vm.deleteVisible, false)
  s.auth.currentTenantRole = 'admin'
  s.resolveRead({ ...s.row, id: 'b' }); await flush()
  assert.equal(s.vm.snapshot, null)
  await s.vm.save(); await s.vm.remove()
  assert.equal(s.writes.length, 0); assert.equal(s.deleted.length, 0)
})

test('删除须确认当前企业名称，成功后清理上下文并在管理应用重新登录', async t => {
  const s = setup(t); await flush()
  s.vm.openDelete(); s.vm.confirmationName = 'wrong'
  await s.vm.remove()
  assert.equal(s.deleted.length, 0)
  s.vm.confirmationName = 'Alpha'
  await s.vm.remove()
  assert.deepEqual(s.deleted, ['a'])
  assert.equal(s.loggedOut(), true)
  assert.deepEqual(s.paths, ['/login'])
})


test('保存和删除失败保留草稿及确认，展示错误且允许重试', async t => {
  const s = setup(t, true); await flush()
  s.vm.name = 'Edited'
  await s.vm.save()
  assert.equal(s.vm.name, 'Edited')
  assert.equal(s.vm.snapshot.name, 'Alpha')
  assert.equal(s.vm.error, 'offline')
  assert.equal(s.vm.busy, false)
  s.vm.openDelete(); s.vm.confirmationName = 'Alpha'
  await s.vm.remove()
  assert.equal(s.vm.deleteVisible, true)
  assert.equal(s.vm.error, 'shared_space_conflict')
  assert.equal(s.loggedOut(), false)
})

 test('复制真实编码，缺失时不复制 UUID，失败可重试', async t => {
  const s = setup(t); await flush()
  s.setCopyResult(false); await s.vm.copyCode()
  assert.equal(s.vm.copyFeedback, 'adminEnterprise.codeCopyFailed')
  s.setCopyResult(true); await s.vm.copyCode()
  assert.equal(s.vm.copyFeedback, 'adminEnterprise.codeCopied')
  assert.deepEqual(s.copies, ['alpha_01', 'alpha_01'])
  s.vm.snapshot.code = null
  assert.equal(s.vm.codeAvailable, false); await s.vm.copyCode(); assert.equal(s.copies.length, 2)
  s.vm.snapshot.code = '  '
  assert.equal(s.vm.codeAvailable, false); await s.vm.copyCode(); assert.equal(s.copies.length, 2)
})
 test('复制期间禁止重复触发，企业切换后丢弃迟到反馈', async t => {
  const s = setup(t); await flush()
  let finish: (value: boolean) => void = () => {}
  s.setCopyResult(new Promise(resolve => { finish = resolve }))
  const pending = s.vm.copyCode(); await s.vm.copyCode(); assert.equal(s.copies.length, 1)
  s.auth.effectiveTenantId = 'b'; await flush(); finish(true); await pending
  assert.equal(s.vm.copyFeedback, ''); assert.equal(s.vm.snapshot, null)
})
 test('卸载后复制结果不再写入状态', async t => {
  const s = setup(t); await flush()
  let finish: (value: boolean) => void = () => {}
  s.setCopyResult(new Promise(resolve => { finish = resolve }))
  const pending = s.vm.copyCode(); s.close(); finish(false); await pending
  assert.equal(s.vm.copyFeedback, '')
})
