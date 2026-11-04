import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import * as pinia from 'pinia'
import ts from 'typescript'

// 面板脚本在隔离的 VM 中执行，依赖（对话页、会话接口、存储）全部替换为测试替身。
const filename = fileURLToPath(new URL('./AssistantPanel.vue', import.meta.url))
const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename })
const panelScript = compileScript(descriptor, { id: 'assistant-panel-test', inlineTemplate: true }).content
const storeScript = readFileSync(new URL('../../stores/assistant.ts', import.meta.url), 'utf8')
const groupingScript = readFileSync(new URL('../sessionGrouping.ts', import.meta.url), 'utf8')
const assistantApiScript = readFileSync(new URL('../../api/assistant.ts', import.meta.url), 'utf8')

function evaluate(source: string, dependencies: Record<string, unknown>, globals = {}) {
  const exports: any = {}
  runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, {
    exports, console, ...globals,
    require(name: string) {
      if (name in dependencies) return dependencies[name]
      throw new Error(`Unexpected component dependency: ${name}`)
    },
  })
  return exports
}

function storage() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) },
    removeItem: (key: string) => { values.delete(key) },
  }
}

const flush = async () => {
  await new Promise(resolve => setImmediate(resolve))
  await vue.nextTick()
}

interface Fixture {
  assistant: any
  auth: any
  chat: { props: Record<string, any>; sends: string[]; created: (id: string) => void }
  listCalls: string[]
  findAll: (predicate: (node: any) => boolean) => any[]
  click: (label: string) => Promise<void>
  clickRow: (text: string) => Promise<void>
  workspaceChanged: () => void
  workspaceRefreshes: () => number
  localStorage: ReturnType<typeof storage>
  close: () => void
}

async function fixture(options: {
  sessions?: Array<{ id: string; title: string; updated_at: string; created_at: string }>
  storedSession?: string
  listFails?: boolean
} = {}): Promise<Fixture> {
  let workspaceRefreshes = 0
  let workspaceChanged: (() => void) | undefined
  const auth = vue.reactive({
    user: { id: 'user-a' },
    effectiveTenantId: 1,
    refreshFromAuthMe: async () => { workspaceRefreshes++; return true },
  })
  const sessionStorage = storage()
  if (options.storedSession) sessionStorage.setItem('nexus:assistant-session:user-a:1', options.storedSession)
  const localStorage = storage()
  const assistantApi = evaluate(assistantApiScript, {
    '@/utils/request': { get: async () => ({ success: true, data: {} }), put: assert.fail },
  })
  const stores = evaluate(storeScript, {
    vue, pinia, './auth': { useAuthStore: () => auth }, '@/api/assistant': assistantApi,
  }, { sessionStorage, localStorage })
  const storeRoot = pinia.createPinia()
  pinia.setActivePinia(storeRoot)
  const assistant = stores.useAssistantStore()

  const chat: Fixture['chat'] = { props: {}, sends: [], created: () => undefined }
  const NexusChatPageStub = vue.defineComponent({
    props: { embedded: Boolean, sessionId: { type: String, default: '' } },
    emits: ['session-created'],
    setup(props, { emit, expose }) {
      chat.props = props
      chat.created = (id: string) => emit('session-created', id)
      expose({
        sendText: async (text: string) => {
          chat.sends.push(`${props.sessionId || ''}|${text}`)
          if (!props.sessionId) chat.created('new-session')
        },
      })
      return () => null
    },
  })
  const emptyComponent = vue.defineComponent({ inheritAttrs: false, render: () => null })
  const listCalls: string[] = []
  const component = evaluate(panelScript, {
    vue,
    'vue-i18n': { useI18n: () => ({ t: (key: string) => key }) },
    'tdesign-vue-next': { MessagePlugin: { error: () => undefined, warning: () => undefined } },
    '@/views/chat/NexusChatPage.vue': NexusChatPageStub,
    '@/components/PanelResizeHandle.vue': emptyComponent,
    '@/api/native-runs': {
      listSessions: async (tenantId: string) => {
        listCalls.push(tenantId)
        if (options.listFails) throw new Error('offline')
        return options.sessions ?? []
      },
    },
    '@/components/sessionGrouping': evaluate(groupingScript, {}),
    '@/stores/assistant': stores,
    '@/stores/auth': { useAuthStore: () => auth },
    '@/utils/assistantDataChange': {
      useAssistantDataChange: (callback: () => void) => { workspaceChanged = callback },
    },
  }, { window: { addEventListener() {}, removeEventListener() {}, innerWidth: 1400 }, document: undefined }).default

  type HostNode = { children: HostNode[]; parent?: HostNode; tag?: string; props: Record<string, any>; style: Record<string, any>; text?: string }
  const node = (tag?: string): HostNode => ({ children: [], tag, props: {}, style: {}, text: undefined })
  const remove = (child: HostNode) => {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
    child.parent = undefined
  }
  const renderer = vue.createRenderer<HostNode, HostNode>({
    createElement: node, createText: node, createComment: node,
    insert(child, parent, anchor) {
      remove(child)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
      child.parent = parent
    },
    remove,
    setElementText(target, text) { target.text = text },
    setText(target, text) { target.text = text },
    patchProp(target, key, _prev, next) { target.props[key] = next },
    parentNode: child => child.parent ?? null,
    nextSibling: child => child.parent?.children[child.parent.children.indexOf(child) + 1] ?? null,
  })
  const app = renderer.createApp(component)
  app.use(storeRoot)
  app.component('t-icon', emptyComponent)
  app.component('t-loading', emptyComponent)
  app.component('t-tooltip', vue.defineComponent({ inheritAttrs: false, setup: (_, { slots }) => () => slots.default?.() }))
  app.component('t-button', vue.defineComponent({ setup: (_, { slots }) => () => vue.h('button', slots.default?.()) }))
  const root = node()
  app.mount(root)

  const findAll = (predicate: (node: HostNode) => boolean): HostNode[] => {
    const found: HostNode[] = []
    const walk = (target: HostNode) => {
      if (predicate(target)) found.push(target)
      target.children.forEach(walk)
    }
    walk(root)
    return found
  }
  const click = async (label: string) => {
    const button = findAll(target => target.props['aria-label'] === label)[0]
    assert.ok(button, `missing button ${label}`)
    button.props.onClick()
    await flush()
  }
  const clickRow = async (text: string) => {
    const row = findAll(target => target.props.class === 'assistant-history__select'
      && target.children.some(child => child.text === text || child.children.some(grand => grand.text === text)))[0]
    assert.ok(row, `missing history row ${text}`)
    row.props.onClick()
    await flush()
  }
  await flush()
  return {
    assistant, auth, chat, listCalls, findAll, click, clickRow, localStorage,
    workspaceChanged: () => workspaceChanged?.(),
    workspaceRefreshes: () => workspaceRefreshes,
    close: () => app.unmount(),
  }
}

test('the conversation area embeds the Nexus chat page bound to the assistant session', async () => {
  const f = await fixture({
    storedSession: 'session-a',
    sessions: [{ id: 'session-a', title: 'A', created_at: '2026-11-01', updated_at: '2026-11-01' }],
  })
  try {
    assert.equal(f.chat.props.embedded, true)
    assert.equal(f.chat.props.sessionId, 'session-a')
    assert.deepEqual(f.listCalls, [1])
  } finally { f.close() }
})

test('a stored session missing from the platform list returns the panel to welcome', async () => {
  const f = await fixture({ storedSession: 'old-weknora-session', sessions: [] })
  try {
    await flush()
    assert.equal(f.assistant.sessionId, '')
    assert.equal(f.chat.props.sessionId, '')
  } finally { f.close() }
})

test('a failed session list keeps the stored session for the chat page to report', async () => {
  const f = await fixture({ storedSession: 'session-a', listFails: true })
  try {
    await flush()
    assert.equal(f.assistant.sessionId, 'session-a')
  } finally { f.close() }
})

test('a session created by the chat page becomes the assistant session', async () => {
  const f = await fixture({ sessions: [] })
  try {
    f.chat.created('new-session')
    await flush()
    assert.equal(f.assistant.sessionId, 'new-session')
    assert.equal(f.chat.props.sessionId, 'new-session')
  } finally { f.close() }
})

test('asking the assistant opens a conversation and sends the question once', async () => {
  const f = await fixture({ sessions: [] })
  try {
    f.assistant.open({ query: 'Summarize the changelog' })
    await flush()
    assert.deepEqual(f.chat.sends, ['|Summarize the changelog'])
    assert.equal(f.assistant.pendingRequest, null)
  } finally { f.close() }
})

test('new conversation returns the panel to welcome', async () => {
  const f = await fixture({ storedSession: 'session-a', sessions: [{ id: 'session-a', title: 'A', created_at: '', updated_at: '' }] })
  try {
    await f.click('assistant.newConversation')
    assert.equal(f.assistant.sessionId, '')
    assert.equal(f.chat.props.sessionId, '')
  } finally { f.close() }
})

test('history lists platform sessions newest first and selecting one switches the conversation', async () => {
  const f = await fixture({
    storedSession: 'session-a',
    sessions: [
      { id: 'session-a', title: 'Older', created_at: '2026-10-01', updated_at: '2026-10-02' },
      { id: 'session-b', title: 'Newer', created_at: '2026-11-01', updated_at: '2026-11-03' },
    ],
  })
  try {
    await f.click('assistant.history')
    const rows = f.findAll(target => target.props.class === 'assistant-history__select')
    assert.equal(rows.length, 2)
    await f.clickRow('Newer')
    assert.equal(f.assistant.sessionId, 'session-b')
    assert.equal(f.chat.props.sessionId, 'session-b')
  } finally { f.close() }
})

test('layout and width persist, with the width kept within bounds', async () => {
  const f = await fixture()
  try {
    assert.equal(f.assistant.layout, 'docked')
    f.assistant.setLayout('floating')
    assert.equal(f.localStorage.getItem('nexus:assistant-layout'), 'floating')
    f.assistant.setWidth(10_000)
    assert.equal(f.assistant.width, 760)
    f.assistant.setWidth(12)
    assert.equal(f.assistant.width, 360)
    assert.equal(f.localStorage.getItem('nexus:assistant-width'), '360')
  } finally { f.close() }
})

test('workspace changes refresh the shared profile even while the panel is hidden', async () => {
  const f = await fixture()
  try {
    assert.equal(f.assistant.visible, false)
    assert.equal(f.workspaceRefreshes(), 0)
    f.workspaceChanged()
    await flush()
    assert.equal(f.workspaceRefreshes(), 1)
  } finally { f.close() }
})
