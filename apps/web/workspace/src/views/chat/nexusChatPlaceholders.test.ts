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
  assert.doesNotMatch(page, /planned\('askAssistant'\)/)
  assert.match(page, /role="tablist"/)
  assert.match(page, /id="chat-panel-artifacts"/)
  assert.match(page, /id="chat-panel-trajectory"/)
  assert.doesNotMatch(page, /class="session-artifacts"/)
  assert.match(page, /listSessionArtifacts\(sessionId\)/)
  assert.doesNotMatch(page, /planned\('sandboxPanel'\)/)
  for (const entry of ['suggestedQuestions', 'fork', 'rewind']) {
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

test('composer keeps supported placeholders after enterprise entry cleanup', () => {
  const composer = read('../../components/Input-field.vue')
  assert.doesNotMatch(composer, /nexusPlanned\('localBrowser'\)/)
  for (const entry of ['webSearch', 'imageUpload', 'attachmentUpload', 'mention', 'modelSelect', 'reasoningEffort']) {
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

test('agent selection uses WeKnora\'s agent button and picker; Nexus-only elements are gone', () => {
  const page = read('./NexusChatPage.vue')
  const template = page.slice(0, page.indexOf('<script'))
  for (const removed of ['NativeWatchdogBanner', 'chat-run-status', 'chat-failure', 'chat-queued', '<t-select']) {
    assert.equal(template.includes(removed), false, removed)
  }
  assert.match(template, /:nexus-agents="agentOptions"/)
  const composer = read('../../components/Input-field.vue')
  assert.match(composer, /class="control-btn agent-mode-btn is-custom"/)
  assert.match(composer, /<NexusAgentSelector /)
  assert.doesNotMatch(read('../../components/NexusAgentSelector.vue'), WEKNORA_APIS)
})
