import { expect, test, type Page, type Route } from '@playwright/test'

const job = {
  id: 'export-1',
  name: '自动化导出任务',
  type: 'export',
  state: 'succeeded',
  progress: 100,
  input: { asset_count: 3 },
  result: { size: 5242880 },
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

async function mockApi(
  page: Page,
  assetRows: Record<string, unknown>[] = [],
  filteredAssetTotal = assetRows.length,
  sessionTokens = tokens,
) {
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/auth/login')) return json(route, sessionTokens)
    if (path.endsWith('/auth/logout')) return route.fulfill({ status: 204 })
    if (path.endsWith('/auth/refresh')) return json(route, sessionTokens)
    if (path.endsWith('/permissions/me')) {
      const role = sessionTokens.user.roles[0]
      const annotator = role === 'annotator'
      return json(route, {
        role,
        menus: (annotator
          ? ['library', 'datasets', 'relations', 'lineage', 'downloads']
          : ['library', 'datasets', 'relations', 'lineage', 'downloads', 'tags', 'formats', 'admin', 'logs']
        ).map(key => ({ key, name: key })),
        actions: (annotator
          ? ['asset_upload', 'asset_edit', 'saved_view_manage', 'dataset_create_edit', 'dataset_members_manage', 'dataset_version_publish', 'relation_manage', 'export_create']
          : ['asset_upload', 'asset_edit', 'asset_delete', 'saved_view_manage', 'dataset_create_edit', 'dataset_members_manage', 'dataset_version_publish', 'dataset_version_restore', 'dataset_delete', 'dataset_model_manage', 'relation_manage', 'relation_revoke', 'export_create', 'trash_manage', 'tag_manage', 'format_manage', 'user_manage']
        ).map(key => ({ key, name: key })),
      })
    }
    if (path.endsWith('/users')) return json(route, { items: [] })
    if (path.endsWith('/roles')) {
      const menus = [
        ['library', '素材库'], ['datasets', '数据集管理'], ['relations', '关联关系'], ['lineage', '模型溯源'],
        ['downloads', '任务中心'], ['trash', '回收站'], ['tags', '标签管理'], ['formats', '格式管理'],
        ['admin', '用户管理'], ['logs', '系统日志'],
      ].map(([key, name]) => ({ key, name }))
      const actions = [
        ['asset_upload', '上传素材', 'library'], ['asset_edit', '编辑素材', 'library'], ['asset_delete', '删除素材', 'library'],
        ['saved_view_manage', '管理保存视图', 'library'], ['dataset_create_edit', '创建编辑数据集', 'datasets'],
        ['dataset_members_manage', '管理数据集成员', 'datasets'], ['dataset_version_publish', '发布数据集版本', 'datasets'],
        ['dataset_version_restore', '恢复数据集版本', 'datasets'], ['dataset_delete', '删除数据集', 'datasets'],
        ['dataset_model_manage', '管理模型关联', 'relations'], ['relation_manage', '管理关联关系', 'relations'],
        ['relation_revoke', '撤销关联关系', 'relations'], ['export_create', '创建导出', 'downloads'],
        ['trash_manage', '管理回收站', 'trash'], ['tag_manage', '管理标签', 'tags'],
        ['format_manage', '管理格式', 'formats'], ['user_manage', '管理用户', 'admin'],
      ].map(([key, name, menu]) => ({ key, name, menu }))
      return json(route, {
        items: [{ key: 'admin', menu_permissions: menus.map(item => item.key), action_permissions: actions.map(item => item.key) }],
        menus,
        actions,
        templates: [],
      })
    }
    if (path.endsWith('/assets/stats')) return json(route, { total: assetRows.length, untagged: assetRows.length, by_type: { other: assetRows.length }, storage: { total: 0, used: 0, free: 0 } })
    if (path.endsWith('/audit-logs')) return json(route, { items: [{ id: 'audit-1', actor_id: 'admin', actor_username: 'admin', action: 'user.updated', object_type: 'user', object_id: 'user-1', object_name: '测试用户', changes: { status: 'active', roles: ['viewer'], password_changed: false, size: 1048576 }, request_id: 'request-1', created_at: '2026-10-08T01:00:00Z' }], page: 1, page_size: 50, total: 1 })
    if (path.endsWith('/assets/trash/items')) return json(route, { items: [], total: 0 })
    if (path.endsWith('/format-definitions')) return json(route, { items: [{ asset_type: 'image', extensions: ['.jpg'] }] })
    if (path.endsWith('/saved-views') || path.endsWith('/tag-definitions')) return json(route, { items: [] })
    if (path.endsWith('/assets/upload-conflicts')) return json(route, {
      total: 1,
      groups: [{ asset_type: 'image', count: 1, items: [{ id: 'old-image', name: 'same.jpg', type: 'image', size: 1024, tags: {}, media: {}, has_active_relations: true }] }],
      items: [{ index: 0, filename: 'same.jpg', asset_type: 'image', existing_count: 1, has_active_relations: true }],
    })
    if (path.endsWith('/assets/upload-sessions/batch')) {
      await new Promise(resolve => setTimeout(resolve, 800))
      return json(route, { items: [{ index: 0, error: { code: 'TEST_DELAY', message: '测试上传结束' } }] })
    }
    if (path.endsWith('/assets/old-image')) return json(route, { id: 'old-image', name: 'same.jpg', type: 'image', size: 1024, tags: {}, media: {}, status: 'ready', created_at: '2026-09-26T01:00:00Z' })
    const assetHistoryMatch = path.match(/\/assets\/([^/]+)\/history$/)
    if (assetHistoryMatch) return json(route, { items: [] })
    const assetDetailMatch = path.match(/\/assets\/([^/]+)$/)
    if (assetDetailMatch) {
      const asset = assetRows.find(item => item.id === assetDetailMatch[1])
      if (asset) return json(route, asset)
    }
    if (path.endsWith('/jobs')) return json(route, { items: [job], total: 1 })
    if (path.endsWith('/datasets/options')) {
      const pageNumber = Number(new URL(request.url()).searchParams.get('page') || 1)
      const items = pageNumber === 1
        ? Array.from({ length: 50 }, (_, index) => ({ id: `dataset-${index + 1}`, name: `数据集 ${index + 1}`, current_version_id: `version-${index + 1}` }))
        : [{ id: 'dataset-51', name: '数据集 51', current_version_id: 'version-51' }]
      return json(route, { items, page: pageNumber, page_size: 50, total: 51 })
    }
    if (/\/datasets\/[^/]+\/versions$/.test(path)) return json(route, { items: [{ id: 'version-1', version: 'v1', member_count: 3 }] })
    if (path.endsWith('/relations')) return json(route, { items: [], total: 0 })
    if (path.endsWith('/assets')) {
      const params = new URL(request.url()).searchParams
      if (params.getAll('asset_type').includes('model')) return json(route, { items: [{ id: 'model-1', name: 'model.pt', type: 'model', extension: '.pt', tags: {} }], total: 1, next_cursor: null })
      return json(route, { items: assetRows, total: filteredAssetTotal, next_cursor: null })
    }
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
  await expect(page.getByText('5.00 MB')).toBeVisible()
  await expect(page.getByRole('option', { name: '素材处理' })).toHaveCount(0)

  await page.getByRole('button', { name: '退出', exact: true }).click()
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  await expect(page.getByText('自动化导出任务')).toHaveCount(0)
})

test('素材库全部数量使用当前筛选结果总数', async ({ page }) => {
  const assetRows = Array.from({ length: 50 }, (_, index) => ({
    id: `image-${index + 1}`,
    name: `图片 ${index + 1}.jpg`,
    type: 'image',
    size: 1024,
    status: 'ready',
    tags: {},
    media: {},
    created_at: '2026-10-02T01:00:00Z',
  }))
  await mockApi(page, assetRows, 100)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')

  await page.locator('.check-list').getByRole('button', { name: /图片/ }).click()

  await expect(page.locator('.content-panel .toolbar').getByText(/当前页/)).toContainText(
    '当前页 50 项 · 全部 100 项',
  )
})

test('素材详情支持方向键切换且编辑备注时不会误切换', async ({ page }) => {
  const assetRows = [
    { id: 'asset-1', name: '第一项.txt', type: 'other', size: 12, status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T01:00:00Z' },
    { id: 'asset-2', name: '第二项.txt', type: 'other', size: 24, status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T02:00:00Z' },
  ]
  await mockApi(page, assetRows)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.locator('.asset-card').first().locator('.asset-preview').click()
  const detail = page.locator('.detail-sheet')
  await expect(detail.getByRole('heading', { name: '第一项.txt' })).toBeVisible()
  await page.keyboard.press('ArrowRight')
  await expect(detail.getByRole('heading', { name: '第二项.txt' })).toBeVisible()
  await detail.getByPlaceholder('请输入素材备注').focus()
  await page.keyboard.press('ArrowLeft')
  await expect(detail.getByRole('heading', { name: '第二项.txt' })).toBeVisible()
  await detail.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(detail.getByRole('heading', { name: '第一项.txt' })).toBeVisible()
})

test('手机宽度下任务状态和操作按钮保持在视口内', async ({ page }) => {
  await mockApi(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /任务中心/ }).click()

  const download = page.getByRole('button', { name: '下载', exact: true })
  await expect(page.locator('.download-table .table-row:not(.head)>:nth-child(7)')).toHaveText('已完成')
  await expect(download).toBeVisible()
  const box = await download.boundingBox()
  expect(box).not.toBeNull()
  expect((box?.x || 0) + (box?.width || 0)).toBeLessThanOrEqual(390)
})

test('弹窗支持标准语义、自动聚焦、Esc 关闭并归还焦点', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  const trigger = page.getByRole('button', { name: '＋ 上传素材' })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '上传素材' })
  await expect(dialog).toBeVisible()
  await expect.poll(() => dialog.evaluate(element => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('关联关系支持数据集分页加载和独立重置', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /关联关系/ }).click()
  await page.getByRole('button', { name: '数据集与模型', exact: true }).click()

  await expect(page.getByPlaceholder('搜索已发布数据集')).toHaveCount(0)
  const steps = page.locator('.relation-builder>article')
  const [firstStep, secondStep] = await Promise.all([steps.nth(0).boundingBox(), steps.nth(1).boundingBox()])
  expect(Math.abs((firstStep?.y || 0) - (secondStep?.y || 0))).toBeLessThan(3)

  await page.getByRole('button', { name: '数据集', exact: true }).click()
  const options = page.locator('.relation-select-options').first()
  await options.evaluate(element => { element.scrollTop = element.scrollHeight; element.dispatchEvent(new Event('scroll')) })
  await expect(page.getByRole('button', { name: '数据集 51', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '数据集 51', exact: true }).click()
  await expect(steps.nth(1).getByRole('button', { name: '重置', exact: true })).toBeVisible()
  await steps.nth(1).getByRole('button', { name: '重置', exact: true }).click()
  await expect(page.getByRole('button', { name: '数据集', exact: true })).toHaveText(/选择数据集/)

  await page.getByRole('button', { name: '选择模型', exact: true }).click()
  await page.getByRole('button', { name: /model\.pt/ }).click()
  await page.getByRole('button', { name: '完成选择', exact: true }).click()
  await expect(steps.nth(0).getByRole('button', { name: '重置', exact: true })).toBeVisible()
  await steps.nth(0).getByRole('button', { name: '重置', exact: true }).click()
  await expect(page.getByText('尚未选择模型')).toBeVisible()
})

test('上传同名文件时按类型展示覆盖和重命名选择', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await expect(page.getByText('没有匹配的素材')).toBeVisible()
  await page.getByRole('combobox', { name: '界面' }).selectOption('command')
  await page.getByRole('button', { name: '＋ 上传素材' }).click()
  const uploadDialog = page.getByRole('heading', { name: '上传素材', exact: true }).locator('..')
  await expect(uploadDialog).toBeVisible()
  await expect.poll(() => uploadDialog.evaluate(element => ({
    overflowY: getComputedStyle(element).overflowY,
    overscroll: getComputedStyle(element).overscrollBehaviorY,
    backgroundLocked: getComputedStyle(document.documentElement).overflow,
  }))).toEqual({ overflowY: 'auto', overscroll: 'contain', backgroundLocked: 'hidden' })
  await uploadDialog.locator('input[type="file"]').setInputFiles({
    name: 'same.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from('image-content'),
  })
  await page.getByRole('button', { name: '开始上传' }).click()

  await expect(page.getByText('图片1 项')).toBeVisible()
  await expect(page.getByText('存在共1项重名文件，请选择：')).toBeVisible()
  await expect(page.getByText('共1项文件')).toBeVisible()
  await expect(page.locator('.upload-conflict-items')).toHaveCount(0)
  await page.locator('.upload-conflict-group').click()
  await expect(page.locator('.upload-conflict-items')).toBeVisible()
  await page.getByRole('button', { name: /same.jpg/ }).click()
  await expect(page.locator('.detail-sheet').getByRole('heading', { name: 'same.jpg' })).toBeVisible()
  await expect.poll(() => page.locator('.detail-sheet').evaluate(element => ({
    overflowY: getComputedStyle(element).overflowY,
    overscroll: getComputedStyle(element).overscrollBehaviorY,
  }))).toEqual({ overflowY: 'auto', overscroll: 'contain' })
  await page.locator('.detail-sheet-stage').click({ position: { x: 20, y: 20 } })
  await expect(page.locator('.detail-sheet')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '覆盖原文件' })).toBeVisible()
  await expect(page.getByRole('button', { name: '重命名并上传' })).toBeVisible()
  await page.getByRole('button', { name: '覆盖原文件' }).click()
  await expect(page.getByText('覆盖原文件会保留关联关系，是否确定？')).toBeVisible()
  const cancelConfirm = page.locator('.confirm-dialog').getByRole('button', { name: '取消', exact: true })
  const acceptConfirm = page.getByRole('button', { name: '确定', exact: true })
  await expect(acceptConfirm).toBeVisible()
  await expect.poll(() => acceptConfirm.evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(110, 231, 183)')
  const [cancelBox, acceptBox] = await Promise.all([cancelConfirm.boundingBox(), acceptConfirm.boundingBox()])
  expect(cancelBox?.width).toBe(acceptBox?.width)
  expect(cancelBox?.height).toBe(acceptBox?.height)
  await acceptConfirm.click()
  await expect(page.locator('.confirm-dialog')).toHaveCount(0)
  await expect(page.getByText('正在上传 · 已处理 0 / 1 项')).toBeVisible()
  await expect(page.getByRole('button', { name: '暂停上传', exact: true })).toBeEnabled()
})

test('普通写入角色不显示破坏性操作', async ({ page }) => {
  const assetRows = [{
    id: 'asset-1', name: '普通素材.jpg', type: 'image', size: 1024,
    status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T01:00:00Z',
  }]
  const annotatorTokens = {
    ...tokens,
    user: { id: 'annotator', username: 'annotator', roles: ['annotator'] },
  }
  await mockApi(page, assetRows, assetRows.length, annotatorTokens)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), annotatorTokens)
  await page.goto('/')

  await expect(page.locator('.profile small')).toHaveText('标注员')
  await page.getByLabel('选择 普通素材.jpg').click()
  await expect(page.locator('.batch-bar').getByRole('button', { name: '删除', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /回收站/ })).toHaveCount(0)
  await page.getByRole('button', { name: '＋ 上传素材' }).click()
  await page.locator('input[type="file"]').setInputFiles({
    name: 'same.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('image-content'),
  })
  await page.getByRole('button', { name: '开始上传' }).click()
  await expect(page.getByRole('button', { name: '覆盖原文件', exact: true })).toHaveCount(0)
  await expect(page.getByText('当前角色不能覆盖原文件，请使用重命名并上传。')).toBeVisible()
})

test('系统管理可以查看并筛选系统日志', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')

  await page.getByRole('button', { name: /系统日志/ }).click()
  await expect(page.getByRole('heading', { name: '系统日志' })).toBeVisible()
  await expect(page.getByText('查看系统内的重要操作记录和请求编号。')).toHaveCount(0)
  await expect(page.locator('.audit-log-table').getByText('修改用户')).toBeVisible()
  await expect(page.locator('.audit-log-table').getByText('用户：测试用户')).toBeVisible()
  await expect(page.locator('.audit-log-table').getByText(/状态：正常/)).toBeVisible()
  await expect(page.getByText('request-1')).toBeVisible()
  await page.locator('.audit-log-table').getByRole('button', { name: '详情', exact: true }).click()
  const detail = page.locator('.audit-detail-sheet')
  await expect(detail.getByRole('heading', { name: '修改用户' })).toBeVisible()
  await expect(detail.getByText('状态', { exact: true })).toBeVisible()
  await expect(detail.getByText('正常', { exact: true })).toBeVisible()
  await expect(detail.getByText('角色', { exact: true })).toBeVisible()
  await expect(detail.getByText('只读访客', { exact: true })).toBeVisible()
  await page.locator('.audit-detail-stage').click({ position: { x: 20, y: 20 } })
  await expect(detail).toHaveCount(0)
  await page.getByPlaceholder('搜索用户、对象、操作或请求 ID').fill('admin')
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await expect(page.getByText('当前页')).toContainText('当前页 1 项')
})

test('自定义用户的菜单权限和操作权限支持全选与取消选择', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')

  await page.getByRole('button', { name: /用户管理/ }).click()
  await page.getByRole('button', { name: '＋ 新增用户', exact: true }).click()
  const userDialog = page.getByRole('heading', { name: '新增用户', exact: true }).locator('..')
  await userDialog.getByLabel('角色').selectOption('custom')

  const menuPermissions = userDialog.getByRole('group', { name: '菜单权限' })
  const actionPermissions = userDialog.getByRole('group', { name: '操作权限' })
  await menuPermissions.getByRole('button', { name: '全选', exact: true }).click()
  await expect(menuPermissions.getByLabel('有权限')).toHaveCount(10)

  await actionPermissions.getByRole('button', { name: '全选', exact: true }).click()
  await expect(actionPermissions.getByLabel('有权限')).toHaveCount(17)
  await actionPermissions.getByRole('button', { name: '取消选择', exact: true }).click()
  await expect(actionPermissions.getByLabel('有权限')).toHaveCount(0)

  await actionPermissions.getByRole('button', { name: '全选', exact: true }).click()
  await menuPermissions.getByRole('button', { name: '取消选择', exact: true }).click()
  await expect(menuPermissions.getByLabel('有权限')).toHaveCount(0)
  await expect(actionPermissions.getByLabel('有权限')).toHaveCount(0)
})
