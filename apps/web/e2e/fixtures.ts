/** 每个用例使用独立浏览器上下文；未声明 API 和页面脚本错误在收尾时失败。 */
import { test as base, expect, type Page, type Request } from '@playwright/test'

export interface ApiReply { status?: number; body: unknown }
export type ApiHandler = (request: Request) => ApiReply | undefined | Promise<ApiReply | undefined>
export interface ApiMock {
  requests: string[]
  handle: (handler: ApiHandler) => void
  signIn: (entries?: string[]) => Promise<void>
}

export const test = base.extend<{ api: ApiMock }>({
  api: [async ({ page }, use) => {
    const unexpected: string[] = [], errors: string[] = [], requests: string[] = [], handlers: ApiHandler[] = []
    let entries = ['workspace', 'enterprise']
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      requests.push(`${request.method()} ${path}`)
      for (const handler of [...handlers].reverse()) {
        const reply = await handler(request)
        if (reply) { await route.fulfill({ status: reply.status ?? 200, json: reply.body }); return }
      }
      if (request.method() === 'GET' && path === '/api/v1/auth/oidc/config') {
        await route.fulfill({ json: { success: true, enabled: false } }); return
      }
      if (request.method() === 'GET' && path === '/api/v1/auth/config') {
        await route.fulfill({ json: { success: true, registration_mode: 'invite_only', complex_password_enabled: false, development_login: false } }); return
      }
      if (request.method() === 'GET' && path === '/api/v1/auth/me') {
        await route.fulfill({ json: { success: true, data: {
          user: { id: 'u', username: 'Owner', email: 'owner@example.test', tenant_id: 'a' },
          tenant: { id: 'a', name: 'Acme' },
          memberships: [{ tenant_id: 'a', tenant_name: 'Acme', role: entries.includes('enterprise') ? 'owner' : 'contributor', entries }],
        } } }); return
      }
      if (request.method() === 'GET' && path === '/api/v1/tenants/a/me/permissions') {
        await route.fulfill({ json: { apis: ['org:manage', 'members:manage', 'enterprise_kbs:manage'] } }); return
      }
      unexpected.push(`${request.method()} ${path}`)
      await route.fulfill({ status: 501, json: { error: 'undeclared_e2e_api' } })
    })
    await use({ requests, handle: handler => handlers.push(handler), signIn: async (allowed = ['workspace', 'enterprise']) => {
      entries = allowed
      await page.addInitScript(() => {
        if (!['http:', 'https:'].includes(location.protocol)) return
        localStorage.setItem('weknora_token', 'e2e-mocked-token')
        localStorage.setItem('weknora_selected_tenant_id', 'a')
      })
    } })
    // 先关闭页面停止轮询，再释放路由，避免收尾期间的请求穿透模拟接口。
    if (!page.isClosed()) await page.close()
    expect(unexpected, '用例必须显式声明所有 API 请求').toEqual([])
    expect(errors, '真实页面不应有脚本错误').toEqual([])
  }, { auto: true }],
})
export { expect }
/** 页面自身不能横向溢出；内部表格滚动不受此限制。 */
export async function expectResponsive(page: Page) {
  for (const width of [1440, 720, 375]) {
    await page.setViewportSize({ width, height: 900 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), { message: `页面在 ${width}px 不应横向溢出` }).toBe(true)
  }
}
