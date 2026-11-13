import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { fixture, flush } from '../test-utils/vueFixture'

function setup(t: Parameters<typeof fixture>[0], policy = true) {
  const f = fixture(t), auth = reactive({ user: { id: 'owner' } })
  const row = { id: 'channel', agent_id: 'agent', kind: 'wechat', status: 'binding', owner_user_id: 'owner', name: 'channel' }
  let creates = 0, polls = 0
  let resolvePoll: (value: unknown) => void = () => {}
  const api = {
    listAgentChannels: async () => ({ items: [row], unverified: [] }),
    fetchChannelPolicy: async () => ({ personal_external_channels: policy }),
    fetchConnectionPermissions: async () => [], fetchWecomApps: async () => [],
    createAgentChannel: async () => { creates++ },
    beginWechatBinding: async () => 'private-qr-content',
    pollWechatBinding: () => { polls++; return new Promise(resolve => { resolvePoll = resolve }) },
  }
  const mounted = f.component(new URL('./IMChannelPanel.vue', import.meta.url), {
    '../stores/auth': { useAuthStore: () => auth }, '../api/enterprise-connections': api,
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) }, 'tdesign-vue-next': { QRCode: {} },
  }, { tenantId: 'tenant', agentId: 'agent', ownership: 'personal' })
  return { ...mounted, auth, row, creates: () => creates, polls: () => polls, finishPoll: () => resolvePoll({ status: 'wait' }) }
}

test('企业策略关闭时不能创建，未实现的机器人类型始终不可创建', async t => {
  const s = setup(t, false)
  await flush()
  assert.equal(s.vm.allowed, false)
  await s.vm.create()
  assert.equal(s.creates(), 0)
  s.vm.externalAllowed = true
  assert.equal(s.vm.allowed, true)
  s.vm.kind = 'qq'
  assert.equal(s.vm.allowed, false)
  await s.vm.create()
  assert.equal(s.creates(), 0)
})

test('二维码只允许所有者绑定；切换账号清空内容并忽略在途轮询', async t => {
  const s = setup(t)
  await flush()
  await s.vm.bind({ ...s.row, owner_user_id: 'other' })
  assert.equal(s.vm.qrContent, '')
  await s.vm.bind(s.row)
  assert.equal(s.vm.qrContent, 'private-qr-content')
  t.mock.timers.tick(1500)
  assert.equal(s.polls(), 1)
  s.auth.user = { id: 'other' }
  assert.equal(s.vm.qrContent, '')
  s.finishPoll()
  await flush()
  t.mock.timers.tick(5000)
  assert.equal(s.polls(), 1)
})

test('关闭绑定弹窗和卸载面板均停止轮询', async t => {
  const s = setup(t)
  await flush()
  await s.vm.bind(s.row)
  s.vm.stopBinding()
  t.mock.timers.tick(5000)
  assert.equal(s.polls(), 0)
  await s.vm.bind(s.row)
  s.close()
  assert.equal(s.vm.qrContent, '')
  t.mock.timers.tick(5000)
  assert.equal(s.polls(), 0)
})
