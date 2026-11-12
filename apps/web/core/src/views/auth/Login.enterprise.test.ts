import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test, { type TestContext } from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import { fixture } from '../../test-utils/vueFixture.ts'
import { canRegister } from './registrationPolicy.ts'

/** 执行真实注册处理器，验证自助注册与邀请注册的接口分流和提交字段。 */
function setup(t: TestContext) {
  const f = fixture(t)
  const file = new URL('./Login.vue', import.meta.url)
  const { descriptor } = parse(readFileSync(file, 'utf8'), { filename: file.pathname })
  const script = compileScript(descriptor, { id: 'enterprise-login' }).content
    .replaceAll('import.meta.env.BASE_URL', "'/'")
    .replace('__expose();', '')
    .replace('return __returned__', '__expose(__returned__); return __returned__')
  const register = t.mock.fn(async (_body: unknown) => ({ success: true }))
  const registerByInvite = t.mock.fn(async (_body: unknown) => ({ success: true }))
  const component = f.evaluate(script, {
    vue: { ...vue, onMounted() {}, onBeforeUnmount() {} },
    'vue-router': { useRouter: () => ({ replace() {} }), useRoute: () => ({ query: {} }) },
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key, tm: () => '', locale: vue.ref('zh-CN') }) },
    'tdesign-vue-next': { MessagePlugin: { success() {}, error: assert.fail } },
    '@nexus-web/core/composables/useRoleLabel': { useRoleLabel: () => ({ formatRole() {}, roleIcon() {} }) },
    '@nexus-web/core/utils/loginNotify': { notifyLoginSuccess() {} },
    '@nexus-web/core/utils/passwordPolicy': { newPasswordRules: () => [] },
    '@nexus-web/core/utils/pendingInvite': { hasPendingInviteToken: () => false, hasPendingInviteCode: () => false },
    '@nexus-web/core/api/auth/index': { register, registerByInvite },
    '@nexus-web/core/stores/auth': { useAuthStore: () => ({ hasValidTenant: true, refreshFromAuthMe: async () => true }) },
    './registrationPolicy': { canRegister },
  }).default
  const { vm } = f.mount(component)
  vm.registerFormRef = { validate: async () => true }
  Object.assign(vm.registerData, { username: 'Owner', email: 'owner@example.test', password: 'example-password', spaceName: '企业 A', companyCode: 'company-a' })
  return { vm, register, registerByInvite }
}

test('自助注册只创建企业并提交企业名称和编码', async t => {
  const { vm, register, registerByInvite } = setup(t)
  vm.registrationMode = 'self_serve'
  await vm.handleRegister()
  assert.equal(register.mock.callCount(), 1)
  assert.equal(registerByInvite.mock.callCount(), 0)
  assert.deepEqual(JSON.parse(JSON.stringify(register.mock.calls[0].arguments[0])), {
    username: 'Owner', email: 'owner@example.test', password: 'example-password',
    space_kind: 'enterprise', space_name: '企业 A', company_code: 'company-a',
  })
})

test('邀请注册加入已有企业，不要求填写或提交新企业字段', async t => {
  const { vm, register, registerByInvite } = setup(t)
  vm.registrationMode = 'invite_register'
  vm.inviteLookup = { tenant_name: 'Existing' }
  vm.inviteToken = 'invitation-token'
  assert.equal(vm.registerRules.spaceName[0].validator(''), true)
  assert.equal(vm.registerRules.companyCode[0].validator(''), true)
  await vm.handleRegister()
  assert.equal(register.mock.callCount(), 0)
  assert.equal(registerByInvite.mock.callCount(), 1)
  assert.deepEqual(JSON.parse(JSON.stringify(registerByInvite.mock.calls[0].arguments[0])), {
    token: 'invitation-token', username: 'Owner', email: 'owner@example.test', password: 'example-password',
  })
})
