import { expect, test, type Page, type Route } from '@playwright/test'

const job = {
  id: 'export-1',
  name: '自动化导出任务',
  type: 'export',
  state: 'succeeded',
  progress: 100,
  input: { asset_count: 3 },
  created_at: '2026-09-25T01:00:00Z',
}

const tokens = {
  access_token: 'test-access',
  access_expires_at: '2099-01-01T00:00:00Z',
  user: { id: 'admin', username: 'admin', roles: ['admin'] },
}

test('刷新 Cookie 失效时清理本地会话并返回登录页', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/refresh')) return json(route, { error: { message: '刷新令牌无效' } }, 401)
    return json(route, {})
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), {
    access_expires_at: tokens.access_expires_at,
    user: tokens.user,
  })
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('cv-archive-session'))).toBeNull()
})

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function mockApi(page: Page) {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/auth/login')) return json(route, tokens)
    if (path.endsWith('/auth/logout')) return route.fulfill({ status: 204 })
    if (path.endsWith('/auth/refresh')) return json(route, tokens)
    if (path.endsWith('/assets/stats')) return json(route, { total: 0, untagged: 0, by_type: {}, storage: { total: 0, used: 0, free: 0 } })
    if (path.endsWith('/assets/trash/items')) return json(route, { items: [], total: 0 })
    if (path.endsWith('/saved-views') || path.endsWith('/tag-definitions') || path.endsWith('/format-definitions')) return json(route, [])
    if (path.endsWith('/jobs')) return json(route, { items: [job], total: 1 })
    if (path.endsWith('/assets')) return json(route, { items: [], total: 0, next_cursor: null })
    return json(route, {})
  })
}

test('未登录不能关闭登录层，退出后清空任务数据', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '关闭登录预览' })).toHaveCount(0)
  await page.getByLabel('用户名', { exact: true }).fill('admin')
  await page.getByLabel('密码', { exact: true }).fill('admin')
  await page.getByLabel('保持登录', { exact: true }).uncheck()
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect.poll(() => page.evaluate(() => ({
    local: localStorage.getItem('cv-archive-session'),
    session: sessionStorage.getItem('cv-archive-session'),
  }))).toEqual({ local: null, session: expect.any(String) })
  await page.getByRole('button', { name: /任务中心/ }).click()
  await expect(page.getByText('自动化导出任务')).toBeVisible()

  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  await expect(page.getByText('自动化导出任务')).toHaveCount(0)
})

test('手机宽度下任务状态和操作按钮保持在视口内', async ({ page }) => {
  await mockApi(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /任务中心/ }).click()

  const download = page.getByRole('button', { name: '下载', exact: true })
  await expect(page.locator('.download-table .table-row:not(.head)>:nth-child(6)')).toHaveText('已完成')
  await expect(download).toBeVisible()
  const box = await download.boundingBox()
  expect(box).not.toBeNull()
  expect((box?.x || 0) + (box?.width || 0)).toBeLessThanOrEqual(390)
})
