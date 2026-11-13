import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
import { runInNewContext } from 'node:vm'

function setup(response: unknown) {
  const calls: Array<{ verb: string; url: string; input: unknown }> = []
  const request = (verb: string) => async (url: string, input?: unknown) => { calls.push({ verb, url, input }); return response }
  const exports: Record<string, any> = {}
  runInNewContext(ts.transpileModule(readFileSync(new URL('./enterprise-members.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
    exports, require: (name: string) => { assert.equal(name, '../utils/request'); return { get: request('GET'), patch: request('PATCH'), post: request('POST'), del: request('DELETE') } },
  })
  return { api: exports, calls }
}
const member = { tenant_id: 'tenant/a', user_id: 'user/a', role: 'contributor', status: 'active', joined_at: '2026-11-13T00:00:00Z', email: 'person@example.com', username: 'person', display_name: '成员' }
const invitation = { id: 'invite/a', user_id: 'user/a', role: 'contributor', status: 'pending', created_at: member.joined_at, email: member.email, display_name: member.display_name }
const link = { id: 'link/a', is_share_link: true, role: 'viewer', status: 'pending', created_at: member.joined_at, expires_at: '2026-11-20T00:00:00Z', invite_url: '/join?token=abc_DEF-123', accepted_count: 0 }

test('成员请求使用企业及用户 ID，角色 PATCH 与移除 DELETE 对应真实接口', async () => {
  const s = setup([member]); await s.api.listEnterpriseMembers('tenant/a')
  assert.equal(s.calls[0].url, '/api/v1/tenants/tenant%2Fa/members')
  const change = setup({ ...member, role: 'admin' }); await change.api.changeEnterpriseMemberRole('tenant/a', 'user/a', 'admin')
  assert.equal(change.calls[0].verb, 'PATCH')
  assert.equal(change.calls[0].url, '/api/v1/tenants/tenant%2Fa/members/user%2Fa')
  assert.deepEqual(JSON.parse(JSON.stringify(change.calls[0].input)), { role: 'admin' })
  await change.api.removeEnterpriseMember('tenant/a', 'user/a')
  assert.equal(change.calls[1].verb, 'DELETE')
  await assert.rejects(setup([{ ...member, tenant_id: 'other' }]).api.listEnterpriseMembers('tenant/a'), /members_response_invalid/)
  await assert.rejects(setup({ ...member, user_id: 'wrong' }).api.changeEnterpriseMemberRole('tenant/a', 'user/a', 'viewer'), /members_response_invalid/)
})

test('人员邀请和链接分别解析，不伪造人员邀请过期时间；拒绝恶意地址', async () => {
  const s = setup([invitation, link]); const rows = await s.api.listEnterpriseInvitations('tenant/a')
  assert.equal(rows[0].kind, 'person'); assert.equal(Object.hasOwn(rows[0], 'expires_at'), false)
  assert.equal(rows[1].kind, 'link'); assert.equal(rows[1].invite_path, link.invite_url)
  for (const url of ['https://evil.example/join?token=abc', '//evil.example/join?token=abc', '/join?token=abc&redirect=https://evil.example', '/join?token=abc#hash']) assert.throws(() => s.api.invitationFromResponse({ ...link, invite_url: url }), /members_response_invalid/)
  for (const bad of [{ ...link, is_share_link: 'true' }, { ...link, accepted_count: -1 }, { ...invitation, role: 'owner' }, { ...invitation, status: 'approved' }]) assert.throws(() => s.api.invitationFromResponse(bad), /members_response_invalid/)
  assert.throws(() => s.api.memberFromResponse({ ...member, status: 'revoked' }), /members_response_invalid/)
})

test('新增账号结果剔除密码字段；链接生成与撤销使用真实端点', async () => {
  const s = setup({ status: 'created', user_id: 'new', password: 'never-retain' })
  const input = { email: member.email, role: 'viewer', username: 'new', password: 'temporary-secret' }
  const row = await s.api.addEnterpriseMember('tenant/a', input)
  assert.equal(Object.hasOwn(row, 'password'), false)
  assert.equal(s.calls[0].url, '/api/v1/tenants/tenant%2Fa/members/by-email')
  assert.equal(s.calls[0].input, input)
  const links = setup(link); await links.api.createEnterpriseInviteLink('tenant/a', 'viewer', 7)
  assert.equal(links.calls[0].url, '/api/v1/tenants/tenant%2Fa/invite-links')
  assert.deepEqual(JSON.parse(JSON.stringify(links.calls[0].input)), { role: 'viewer', expires_in_days: 7 })
  await links.api.revokeEnterpriseInvitation('tenant/a', 'link/a')
  assert.equal(links.calls[1].url, '/api/v1/tenants/tenant%2Fa/invitations/link%2Fa')
  assert.equal(links.calls[1].verb, 'DELETE')
})

test('待审批申请与邀请分开解析，状态和角色错误时拒绝消费', async () => {
  const application = { ...invitation, unit_id: null, message: '希望加入' }
  const s = setup([application])
  assert.equal((await s.api.listEnterpriseApplications('tenant/a'))[0].message, '希望加入')
  assert.equal(s.calls[0].url, '/api/v1/tenants/tenant%2Fa/join-requests')
  for (const bad of [{ ...application, status: 'approved' }, { ...application, role: 'owner' }, { ...application, message: {} }]) assert.throws(() => s.api.applicationFromResponse(bad), /members_response_invalid/)
})

test('批准传递部门与角色并校验回执；拒绝提交原因并使用正确企业路径', async () => {
  const s = setup({ user_id: 'user/a', role: 'viewer', status: 'active' })
  await s.api.approveEnterpriseApplication('tenant/a', 'application/a', { unit_id: 'department', role: 'viewer' }, 'user/a')
  assert.equal(s.calls[0].url, '/api/v1/tenants/tenant%2Fa/join-requests/application%2Fa/approve')
  assert.deepEqual(s.calls[0].input, { unit_id: 'department', role: 'viewer' })
  await s.api.rejectEnterpriseApplication('tenant/a', 'application/a', '不符合条件')
  assert.equal(s.calls[1].url, '/api/v1/tenants/tenant%2Fa/join-requests/application%2Fa/reject')
  assert.deepEqual(JSON.parse(JSON.stringify(s.calls[1].input)), { reason: '不符合条件' })
  await assert.rejects(setup({ user_id: 'wrong', role: 'viewer', status: 'active' }).api.approveEnterpriseApplication('tenant/a', 'application/a', { unit_id: 'department', role: 'viewer' }, 'user/a'), /members_response_invalid/)
  await assert.rejects(setup({ user_id: 'user/a', role: 'admin', status: 'active' }).api.approveEnterpriseApplication('tenant/a', 'application/a', { unit_id: 'department', role: 'viewer' }, 'user/a'), /members_response_invalid/)
})
