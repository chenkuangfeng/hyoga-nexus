import { test, expect, expectResponsive, type ApiMock } from './fixtures'
import type { Page } from '@playwright/test'

function mockUsage(api: ApiMock, permissions: string[], failMembers = false) {
  const writes: Record<string, unknown>[] = [], queries: URL[] = []
  let limits: Record<string, unknown>[] = []
  api.handle(request => {
    const url = new URL(request.url()), path = url.pathname
    if (path === '/api/v1/tenants/a/me/permissions') return { body: { apis: permissions } }
    if (path === '/api/v1/tenants/a/admin/usage') {
      queries.push(url)
      return { body: { items: [{ key: url.searchParams.get('group_by') === 'user' ? 'u1' : '2026-11-01', runs: 2, input_tokens: 10, output_tokens: 20, cache_read_tokens: 100, cache_creation_tokens: 50 }] } }
    }
    if (path === '/api/v1/tenants/a/admin/usage/limits') {
      if (request.method() === 'PUT') {
        const input = request.postDataJSON() as Record<string, unknown>; writes.push(input)
        limits = input.monthly_tokens === null ? [] : [{ id: 'limit-1', scope_id: input.scope_id || 'a', used_this_month: 30, ...input }]
        return { body: { limit: limits[0] || null } }
      }
      return { body: { items: limits } }
    }
    if (permissions.includes('members:manage') && path === '/api/v1/tenants/a/admin/members') return failMembers
      ? { status: 503, body: { error: 'directory_unavailable' } }
      : { body: [{ tenant_id: 'a', user_id: 'u1', role: 'contributor', status: 'active', joined_at: '2026-11-01T00:00:00Z', suspended_at: null, display_name: 'Alice', username: 'alice', email: 'alice@example.test' }] }
    if (permissions.includes('org:manage') && path === '/api/v1/tenants/a/admin/org-units/tree') return { body: [{ id: 'd1', parent_id: null, name: 'Research', status: 'active', source: 'manual', sync_managed: false, member_count: 1 }] }
  })
  return { writes, queries }
}
async function choose(page: Page, selector: string, label: string) {
  await page.locator(selector).click()
  await page.locator('.t-select-option:visible').filter({ hasText: label }).click()
}

test('用量按实际查询分组展示，成员限额确认后保存和移除', async ({ page, api }) => {
  await api.signIn()
  const mock = mockUsage(api, ['models:manage', 'members:manage', 'org:manage'])
  await page.goto('usage')
  await expect(page.locator('.summary strong')).toHaveText(['2', '10', '20', '30'])
  await page.locator('input[type="date"]').nth(0).fill('2026-11-01')
  await page.locator('input[type="date"]').nth(1).fill('2026-11-30')
  await choose(page, '.filters .t-select', '按成员')
  await page.getByRole('button', { name: '查询', exact: true }).click()
  await expect(page.locator('.table-wrap').first().locator('tbody')).toContainText('Alice')
  expect(mock.queries.at(-1)!.searchParams.get('start')).toBe('2026-11-01')
  expect(mock.queries.at(-1)!.searchParams.get('end')).toBe('2026-11-30')
  await choose(page, '.filters .t-select', '按日期')
  await expect(page.locator('.table-wrap').first().locator('tbody')).toContainText('Alice')
  await choose(page, '.limit-form .t-select', '成员: Alice')
  await page.locator('.limit-form .t-input-number input').fill('500')
  await page.getByRole('button', { name: '保存上限', exact: true }).click()
  await expect(page.locator('.t-dialog:visible')).toContainText('Alice')
  await expect(page.locator('.t-dialog:visible')).toContainText('500')
  expect(mock.writes).toHaveLength(0)
  await page.locator('.t-dialog:visible .t-dialog__footer button').last().click()
  await expect(page.locator('.limits tbody')).toContainText('Alice')
  expect(mock.writes).toEqual([{ scope_kind: 'user', scope_id: 'u1', monthly_tokens: 500 }])
  await page.locator('.limits tbody').getByRole('button', { name: '移除', exact: true }).click()
  await expect(page.locator('.t-dialog:visible')).toBeVisible()
  await page.locator('.t-dialog:visible .t-dialog__footer button').last().click()
  await expect(page.locator('.limits tbody')).toContainText('尚未设置月度上限')
  expect(mock.writes[1]).toEqual({ scope_kind: 'user', scope_id: 'u1', monthly_tokens: null })
  await expectResponsive(page)
})

test('缺少目录权限时不读取目录，只允许企业范围查询和设置', async ({ page, api }) => {
  await api.signIn()
  const mock = mockUsage(api, ['models:manage'])
  await page.goto('usage')
  await expect(page.locator('.summary strong')).toHaveText(['2', '10', '20', '30'])
  await page.locator('.filters .t-select').click()
  await expect(page.locator('.t-select-option:visible')).toHaveText(['按日期'])
  await page.keyboard.press('Escape')
  await page.locator('.limit-form .t-select').click()
  await expect(page.locator('.t-select-option:visible')).toHaveText(['整个企业'])
  await page.keyboard.press('Escape')
  await page.locator('.limit-form .t-input-number input').fill('1000')
  await page.getByRole('button', { name: '保存上限', exact: true }).click()
  await page.locator('.t-dialog:visible .t-dialog__footer button').last().click()
  await expect(page.locator('.limits tbody')).toContainText('1,000')
  expect(mock.writes).toEqual([{ scope_kind: 'tenant', monthly_tokens: 1000 }])
  expect(api.requests.some(path => /\/members|\/org-units/.test(path))).toBe(false)
})

test('可选成员目录失败显示警告，企业用量和其他可用范围仍可操作', async ({ page, api }) => {
  await api.signIn()
  mockUsage(api, ['models:manage', 'members:manage', 'org:manage'], true)
  await page.goto('usage')
  await expect(page.locator('.summary strong')).toHaveText(['2', '10', '20', '30'])
  await expect(page.locator('.t-alert--warning')).toContainText('成员目录读取失败')
  await page.locator('.limit-form .t-select').click()
  await expect(page.locator('.t-select-option:visible')).toHaveText(['整个企业', '部门: Research'])
  await page.keyboard.press('Escape')
  await expectResponsive(page)
})
