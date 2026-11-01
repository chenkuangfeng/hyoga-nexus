/** Browser behavior tests with deterministic API/SSE fixtures; start Vite first. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../apps/web/package.json', import.meta.url))
const { chromium } = require('playwright')
const browser = await chromium.launch({ headless: true })
const baseURL = process.env.NEXUS_WEB_TEST_URL || 'http://127.0.0.1:5173'
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const consoleErrors = []
page.on('pageerror', error => consoleErrors.push(error.message))
let snapshotRefreshes = 0, sessions = [], messages = [], run = null, events = [], sends = 0, responses = 0, reconnects = 0, corrections = 0
const makeEvent = (sequence, event_type, payload = {}) => ({ event_id: `event-${run.id}-${sequence}`, run_id: run.id, sequence, event_type, payload })
const json = value => ({ contentType: 'application/json', body: JSON.stringify(value) })
await page.route('**/api/v1/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
  if (new URL(request.url()).pathname.endsWith('/auth/me')) return route.fulfill(json({ user_id: 'user-1', display_name: '测试用户', providers: ['password'] }))
  if (path.endsWith('/tenants')) return route.fulfill(json([{ id: 'tenant', name: '开发空间' }]))
  if (path.endsWith('/agents')) return route.fulfill(json([{ id: 'agent', name: '研究助手', runtime_type: 'native', published_version_id: 'version' }]))
  if (path.endsWith('/sessions') && method === 'POST') {
    const created = { id: 'session', title: '验收会话', agent_version_id: 'version' }; sessions = [created]
    return route.fulfill(json(created))
  }
  if (path.endsWith('/memory-snapshot') && method === 'GET') return route.fulfill(json({ exists: true, created_at: '2026-11-01T08:00:00Z', stale: false }))
  if (path.endsWith('/memory-snapshot/refresh') && method === 'POST') { snapshotRefreshes++; return route.fulfill({ status: 204, body: '' }) }
  if (path.endsWith('/sessions')) return route.fulfill(json(sessions))
  if (path.endsWith('/messages')) return route.fulfill(json({ messages, latest_run: run }))
  if (path.endsWith('/runs') && method === 'POST') {
    sends++
    assert.ok(request.headers()['idempotency-key'])
    const body = request.postDataJSON()
    run = { id: `run-${sends}`, status: 'running', error_code: null }
    messages.push({ id: `user-${sends}`, run_id: run.id, sequence: messages.length + 1, role: 'user', content: body.message })
    events = [makeEvent(1, 'run.queued', { status: 'queued' }), makeEvent(2, 'run.started', { status: 'running' }),
      makeEvent(3, 'message.delta', { turn: 1, text: '<img src=x onerror="window.injected=true"> 安全内容' })]
    if (sends === 1) events.push(makeEvent(4, 'tool.started', { invocation_id: 'tool-1', name: 'ask_user' }),
      makeEvent(5, 'tool.completed', { invocation_id: 'tool-1', status: 'completed', summary: '选择市场' }),
      makeEvent(6, 'input.requested', { input_request_id: 'input-1', question: '请选择研究市场', candidates: ['A股', '港股'] }),
      makeEvent(7, 'run.waiting_input', { status: 'waiting_input' }))
    return route.fulfill(json(run))
  }
  if (path.endsWith('/input') && method === 'POST') {
    responses++; assert.ok(request.headers()['idempotency-key'])
    messages.push({ id: 'answer', run_id: run.id, sequence: messages.length + 1, role: 'user', content: request.postDataJSON().response })
    events.push(makeEvent(8, 'input.received', { input_request_id: 'input-1' }), makeEvent(9, 'run.started'),
      makeEvent(10, 'message.delta', { turn: 2, text: '收到回答，已完成。' }), makeEvent(11, 'run.completed', { status: 'completed' }))
    messages.push({ id: 'assistant-before-input', run_id: run.id, sequence: messages.length + 1, role: 'assistant', content: '请选择研究市场' },
      { id: 'assistant-after-input', run_id: run.id, sequence: messages.length + 2, role: 'assistant', content: '收到回答，已完成。' })
    run.status = 'completed'; return route.fulfill(json(run))
  }
  if (path.endsWith('/steer') && method === 'POST') {
    corrections++; assert.ok(request.headers()['idempotency-key'])
    assert.equal(request.postDataJSON().content, '仅使用已验证信息')
    return route.fulfill(json({ id: 'correction', status: 'queued' }))
  }
  if (path.endsWith('/cancel')) {
    run.status = 'cancelled'; events.push(makeEvent(4, 'run.cancelled', { status: 'cancelled' }))
    return route.fulfill(json(run))
  }
  if (path.endsWith('/events')) {
    const after = Math.max(Number(url.searchParams.get('after_sequence') || 0), Number(request.headers()['last-event-id'] || 0))
    if (after) reconnects++
    const frames = events.filter(event => event.sequence > after)
    // A duplicated persisted frame must not duplicate text in the UI.
    if (!after && frames.length >= 3) frames.splice(3, 0, frames[2])
    return route.fulfill({ contentType: 'text/event-stream', body: frames.map(event => `id: ${event.sequence}\nevent: run.event\ndata: ${JSON.stringify(event)}\n\n`).join('') })
  }
  throw new Error(`Unexpected request: ${method} ${path}`)
})
try {
  await page.goto(baseURL)
  await page.getByRole('button', { name: '新建会话', exact: true }).click()
  // The memory snapshot control is shown for the open session and refreshes it on request.
  await page.getByText('记忆索引已固定，与当前记忆一致。', { exact: true }).waitFor()
  const refreshed = page.waitForResponse(response => response.url().endsWith('/memory-snapshot/refresh'))
  await page.getByRole('button', { name: '刷新记忆快照', exact: true }).click()
  await refreshed
  assert.equal(snapshotRefreshes, 1)
  await page.getByLabel('你的消息', { exact: true }).fill('研究市场')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await page.getByLabel('智能体需要你的回答', { exact: true }).waitFor()
  assert.equal(await page.locator('.message-text').filter({ hasText: '安全内容' }).count(), 1)
  assert.equal(await page.locator('.message-text img').count(), 0)
  assert.equal(await page.evaluate(() => window.injected), undefined)
  assert.match(await page.locator('summary').innerText(), /ask_user.*已完成/)
  await page.getByRole('button', { name: 'A股', exact: true }).click()
  assert.equal(await page.getByLabel('智能体需要你的回答', { exact: true }).inputValue(), 'A股')
  await page.getByRole('button', { name: '提交回答', exact: true }).click()
  await page.getByText('收到回答，已完成。', { exact: true }).waitFor()
  assert.equal(responses, 1)
  const content = await page.locator('.message-list').innerText()
  assert.ok(content.indexOf('选择市场') < content.indexOf('A股'))
  assert.ok(content.indexOf('A股') < content.indexOf('收到回答'))
  await page.getByLabel('你的消息', { exact: true }).fill('第二次请求')
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await page.getByText('连接中断，正在自动重连', { exact: true }).waitFor()
  await page.getByLabel('追加执行指令', { exact: true }).fill('仅使用已验证信息')
  await page.getByRole('button', { name: '追加指令', exact: true }).click()
  await page.getByText('指令已排队，将在下一回合生效', { exact: true }).waitFor()
  assert.equal(corrections, 1)
  await page.getByRole('button', { name: '重新连接', exact: true }).click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '停止运行', exact: true }).click()
  await page.getByText('已取消', { exact: true }).waitFor()
  assert.equal(sends, 2)
  // Explicit reconnect starts at the last cursor, never creates a new Run.
  await page.waitForTimeout(1200)
  assert.ok(reconnects > 0)
  assert.equal(sends, 2)
  await page.screenshot({ path: '/tmp/hyoga-p2-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 375, height: 812 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await page.getByLabel('你的消息', { exact: true }).focus()
  assert.equal(await page.getByLabel('你的消息', { exact: true }).evaluate(element => element === document.activeElement), true)
  await page.screenshot({ path: '/tmp/hyoga-p2-mobile.png', fullPage: true })
  await page.route('**/api/v1/tenants', route => route.fulfill({ status: 403, ...json({ error: { message: 'Access denied' } }) }))
  await page.getByRole('button', { name: '刷新会话', exact: true }).click()
  await page.getByText('无权访问或内容已不可用：Access denied', { exact: true }).waitFor()
  assert.equal(await page.locator('.chat-message').count(), 0)
  assert.deepEqual(consoleErrors, [])
  console.log('PASS: send, safe rendering, tool status, input continuation, event deduplication, reconnect, cancellation, keyboard focus, 375px layout')
} finally { await browser.close() }
