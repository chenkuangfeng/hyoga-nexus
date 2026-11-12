/**
 * The Nexus agent and model pages must call only platform endpoints
 * (openspec 2026-11-05-weknora-agent-tool-model-settings, task 4.2). WeKnora's `/api/v1/agents*`
 * and `/api/v1/models*` do not exist on the Nexus backend.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const files = [
  './NexusAgentList.vue',
  './NexusAgentEditorModal.vue',
  '../settings/NexusModelSettings.vue',
  '../settings/NexusModelEditorDialog.vue',
  '../../../../core/src/api/nexus-agents.ts',
  '../../../../core/src/api/nexus-models.ts',
]

const forbidden = [
  /['"`]\/api\/v1\/agents/,
  /['"`]\/api\/v1\/models/,
  /from ['"](?:@\/|@nexus-web\/core\/)api\/agent['"]/,
  /from ['"](?:@\/|@nexus-web\/core\/)api\/model['"]/,
  /from ['"](?:@\/|@nexus-web\/core\/)stores\/(chatResources|editorResources|modelProviders|organization)['"]/,
]

for (const file of files) {
  test(`${file} uses only Nexus platform APIs`, () => {
    const source = readFileSync(new URL(file, import.meta.url), 'utf8')
    for (const pattern of forbidden) assert.doesNotMatch(source, pattern)
  })
}

test('router and settings point to the Nexus pages', () => {
  const router = readFileSync(new URL('../../router/index.ts', import.meta.url), 'utf8')
  assert.match(router, /path: "agents",[\s\S]{0,200}NexusAgentList\.vue/)
  const settings = readFileSync(new URL('../settings/Settings.vue', import.meta.url), 'utf8')
  assert.match(settings, /import ModelSettings from '\.\/NexusModelSettings\.vue'/)
  const phase1 = readFileSync(new URL('../../config/phase1.ts', import.meta.url), 'utf8')
  assert.match(phase1, /'models'/)
})
