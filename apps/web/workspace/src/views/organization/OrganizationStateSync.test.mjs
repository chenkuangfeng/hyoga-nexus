import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const listSource = readFileSync(new URL('./OrganizationList.vue', import.meta.url), 'utf8')
const settingsSource = readFileSync(new URL('./OrganizationSettingsModal.vue', import.meta.url), 'utf8')
const kbShareSource = readFileSync(
  new URL('../../../../core/src/components/knowledge-editor/settings/KBShareSettings.vue', import.meta.url),
  'utf8'
)
const agentShareSource = readFileSync(
  new URL('../../components/AgentShareSettings.vue', import.meta.url),
  'utf8'
)
const storeSource = readFileSync(
  new URL('../../../../core/src/stores/organization.ts', import.meta.url),
  'utf8'
)

test('organization list directly derives cards from the store', () => {
  assert.match(
    listSource,
    /const organizations = computed<OrgWithUI\[\]>\(\(\) => orgStore\.organizations\)/
  )
  assert.doesNotMatch(listSource, /organizations\.value = newOrgs\.map/)
})

test('join flows and searchable cache are coordinated by the store', () => {
  assert.match(listSource, /orgStore\.join\(inviteCode\.value\)/)
  assert.match(listSource, /orgStore\.joinById\(/)
  assert.match(listSource, /orgStore\.fetchSearchableOrganizations\(/)
  assert.doesNotMatch(listSource, /const searchCache = ref/)
})

test('organization settings writes use store actions', () => {
  for (const action of [
    'updateOrganization',
    'reviewOrganizationJoinRequest',
    'inviteOrganizationMember',
    'requestOrganizationRoleUpgrade',
    'unshareKnowledgeBase',
    'unshareAgent'
  ]) {
    assert.match(settingsSource, new RegExp(`orgStore\\.${action}\\(`))
  }
})

test('knowledge base shares use store actions and agent shares use the dedicated API', () => {
  assert.match(kbShareSource, /orgStore\.shareKnowledgeBase\(/)
  assert.match(kbShareSource, /orgStore\.unshareKnowledgeBase\(/)
  assert.match(kbShareSource, /orgStore\.changeKnowledgeBaseSharePermission\(/)
  // 智能体共享已改为直接调用 agent-share API（见 AgentShareSettings.vue 与 api/agent-share）。
  assert.match(agentShareSource, /from '@nexus-web\/core\/api\/agent-share\/index'/)
  assert.match(agentShareSource, /await shareAgent\(/)
  assert.match(agentShareSource, /await unshareAgent\(/)
})

test('store invalidates all affected organization caches after sharing', () => {
  assert.match(
    storeSource,
    /invalidateOrganizationData\(\{ sharedKnowledgeBases: true \}\)/
  )
  assert.match(
    storeSource,
    /invalidateOrganizationData\(\{ sharedAgents: true, sharedKnowledgeBases: true \}\)/
  )
  assert.match(storeSource, /adjustOrganizationResourceCount\(/)
})
