import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const agentListSource = readFileSync(new URL('../agent/AgentList.vue', import.meta.url), 'utf8')
const knowledgeBaseEditorSource = readFileSync(
  new URL('../../../../core/src/components/knowledge-editor/KnowledgeBaseEditorModal.vue', import.meta.url),
  'utf8',
)
const agentEditorSource = readFileSync(new URL('../agent/AgentEditorModal.vue', import.meta.url), 'utf8')

test('resource editor links retain focus and reject stale editor loads', () => {
  assert.match(
    agentListSource,
    /editingAgent\.value\?\.id === agent\.id[\s\S]*focusAgentEditorSection\(requestedSection\)[\s\S]*editorVisible\.value = false\s*await nextTick\(\)\s*if \(generation !== editOpenGeneration\) return[\s\S]*editorVisible\.value = true/,
  )
  assert.match(agentListSource, /const agent = resolveAgentForEdit\([\s\S]*if \(!agent\) return[\s\S]*router\.replace/)
  // 加载遮罩由 SettingsModalShell 的 :loading 渲染（旧写法是模板内 v-if），两种都接受
  assert.match(agentEditorSource, /(?:v-if|:loading)="editorInitializing"[\s\S]*:disabled="editorInitializing"/)
  assert.match(agentEditorSource, /generation !== editorInitializationGeneration \|\| !props\.visible/)
  assert.match(knowledgeBaseEditorSource, /(?:v-if|:loading)="loading"[\s\S]*:disabled="loading[^\"]*"/)
  assert.match(knowledgeBaseEditorSource, /isCurrentKBLoad\(generation, kbId\)/)
  assert.match(knowledgeBaseEditorSource, /isCurrentGeneration\(generation\)/)
  assert.match(knowledgeBaseEditorSource, /setTimeout\(\(\) => \{\s*if \(props\.visible\) return\s*resetState\(\)/)
})
