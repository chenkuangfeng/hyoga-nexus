/**
 * The Nexus chat page copies WeKnora's chat UI; entries without a platform backend are placeholders
 * (openspec 2026-11-04-weknora-chat-dialog, scope change 2026-11-05). These checks keep the page off
 * WeKnora endpoints and keep the placeholder wiring in the reused components.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

const WEKNORA_APIS = /from ['"]@\/api\/(chat|message-suggestion|mcp-service|embed|automation|knowledge-base|wiki)(\/[^'"]*)?['"]/

test('chat page and header import only platform APIs', () => {
  for (const file of ['./NexusChatPage.vue', '../../components/NexusChatHeader.vue']) {
    assert.doesNotMatch(read(file), WEKNORA_APIS, file)
  }
})

test('page provides Nexus actions and the WeKnora prompt dock', () => {
  const page = read('./NexusChatPage.vue')
  assert.match(page, /provideNexusChatActions\(/)
  assert.match(page, /providePromptDock\(/)
  for (const entry of ['suggestedQuestions', 'sandboxPanel', 'fork', 'rewind', 'askAssistant']) {
    assert.match(page, new RegExp(`planned\\('${entry}'\\)`), entry)
  }
})

test('reused WeKnora cards submit through Nexus actions before WeKnora APIs', () => {
  for (const file of ['./components/ToolApprovalCard.vue', './components/AskUserCard.vue']) {
    const source = read(file)
    const nexus = source.indexOf('if (nexusActions)')
    const weknora = source.indexOf('const { resumed } = await')
    assert.ok(nexus > 0 && nexus < weknora, file)
  }
  for (const file of ['./components/AgentStreamDisplay.vue', './components/botmsg.vue']) {
    const source = read(file)
    assert.match(source, /nexusActions\.planned\('addToKnowledgeBase'\)/, file)
    assert.match(source, /nexusActions\.planned\('artifacts'\)/, file)
  }
})

test('composer shows every WeKnora control as a placeholder in nexus mode', () => {
  const composer = read('../../components/Input-field.vue')
  for (const entry of ['localBrowser', 'webSearch', 'imageUpload', 'attachmentUpload', 'mention', 'modelSelect', 'reasoningEffort']) {
    assert.match(composer, new RegExp(`nexusPlanned\\('${entry}'\\)`), entry)
  }
})

test('header keeps every WeKnora menu entry', () => {
  const header = read('../../components/NexusChatHeader.vue')
  for (const entry of ['renameSession', 'sessionGrants', 'deleteSession']) {
    assert.match(header, new RegExp(`'${entry}'`), entry)
  }
  assert.match(header, /emit\('copy-markdown'\)/)
})
