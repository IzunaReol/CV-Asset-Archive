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

test('品牌图标在页头、登录页和浏览器标签中保持一致', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  const logo = page.locator('.brand img.brand-mark')
  await expect(logo).toBeVisible()
  await expect(page.locator('.login-brand img.brand-mark')).toHaveAttribute('src', await logo.getAttribute('src') || '')
  const iconPath = await page.locator('link[rel="icon"]').getAttribute('href')
  expect(iconPath?.split('?')[0]).toBe((await logo.getAttribute('src'))?.split('?')[0])
  const icon = await page.request.get(iconPath!)
  expect(icon.ok()).toBeTruthy()
  expect(icon.headers()['content-type']).toContain('image/svg+xml')
  await expect(logo).toHaveJSProperty('naturalWidth', 64)
  await page.locator('.login-brand').screenshot({ path: 'test-results/brand-preview.png' })
})

test('系统概览独立页面可加载、刷新并跳转', async ({ page }) => {
  let loads = 0
  await mockApi(page)
  await page.route('**/api/v1/system/overview', route => {
    loads++
    return json(route, { counts: { assets: 10, datasets: 2, relations: 3, running_jobs: 1, failed_jobs: 0 }, asset_types: { video: 2, image: 7, annotation: 1 }, asset_storage_by_type: { video: { count: 2, size: 200 }, image: { count: 7, size: 700 }, annotation: { count: 1, size: 100 } }, recent_activity: [] })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await expect(page.locator('.sidebar .nav-label')).toHaveText(['概览', '资产管理', '系统管理'])
  await expect(page.locator('.sidebar nav .nav-label').first().locator('xpath=following-sibling::button[position()<=2]')).toHaveText(['◈系统概览', '▦项目概览'])
  await expect(page.locator('.overview-cards')).toContainText('10')
  await expect(page.locator('.overview-types > div > span')).toHaveText(['图片', '视频', '标注'])
  await expect(page.locator('.overview-pie')).toBeVisible()
  await expect(page.locator('.overview-pie-legend > div > span')).toHaveText(['图片', '视频', '标注'])
  await expect(page.locator('.overview-pie-legend > div > b')).toHaveText(['70.0%', '20.0%', '10.0%'])
  await page.getByRole('button', { name: '刷新' }).click()
  await expect.poll(() => loads).toBe(2)
  await page.getByRole('button', { name: '查看素材' }).click()
  await expect(page.getByRole('heading', { name: '素材库' })).toBeVisible()
})

test('侧栏存储空间只在获取到有效容量时展示', async ({ page }) => {
  await mockApi(page)
  let available = false
  await page.route('**/api/v1/assets/stats', route => json(route, {
    total:0, untagged:0, by_type:{},
    storage: available ? {total:1000, used:250, free:750} : {total:0, used:0, free:0},
  }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  const firstStats = page.waitForResponse('**/api/v1/assets/stats')
  await page.goto('/')
  await firstStats
  await expect(page.locator('.sidebar .storage')).toHaveCount(0)
  available = true
  await page.locator('.sidebar nav').getByRole('button', {name:/素材库/}).click()
  await expect(page.locator('.sidebar .storage')).toContainText('剩余 75%')
})

test('项目概览可多选项目、展示数据集当前成员与模型文件', async ({ page }) => {
  await mockApi(page)
  const queried: string[][] = []
  await page.route(/\/api\/v1\/projects\/overview(?:\?.*)?$/, route => {
    const requested = new URL(route.request().url()).searchParams.getAll('projects')
    queried.push(requested)
    const names = requested.length ? requested : ['烟火检测', '安全帽']
    return json(route, {
      available_projects: ['烟火检测', '安全帽'], selected_projects: names,
      summary: { project_count: names.length, dataset_count: 1, model_count: 1, file_count: 1 },
      projects: names.map(name => ({
        name, dataset_count: 1,
        dataset_counts: { image: 2, video: 0, annotation: 2, archive: 0, other: 0 }, datasets: [{ id: 'dataset-1', name: '烟火训练集', current_version: 'v1', counts: { image: 2, video: 0, annotation: 2, archive: 0, other: 0 } }],
        model_count: 1, models: [{ id: 'model-1', name: 'fire.pt', remark: '基线模型', sources: ['数据集关联', '项目标签'], versions: ['烟火训练集 · v1'], configured_parameters: [{ id: 'accuracy', name: '准确率', category: '图像分类', value: '0.98' }] }],
        file_count: 1, file_counts: { image: 1, video: 0, annotation: 0, archive: 0, other: 0 },
        files: [{ id: 'file-1', name: 'sample.jpg', type: 'image', size: 1024, tags: { algorithm: ['烟火识别'] } }], files_truncated: false,
      })),
    })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /项目概览/ }).click()
  await expect(page.getByRole('heading', { name: '项目概览' })).toBeVisible()
  await expect(page.locator('.project-section')).toHaveCount(2)
  const statsBox = await page.locator('.project-stat-grid').boundingBox()
  const sectionBox = await page.locator('.project-section').first().boundingBox()
  expect(statsBox && sectionBox && sectionBox.y - (statsBox.y + statsBox.height)).toBeGreaterThanOrEqual(20)
  await expect(page.locator('.project-stat-grid')).toContainText('1')
  await expect(page.locator('.project-model-card').first()).not.toContainText('待接入 MLflow')
  await expect(page.locator('.project-model-card').first().locator('.project-model-parameters')).toHaveText('准确率：0.98')
  await expect(page.getByText('跨项目重复关联的对象在顶部总数中只计算一次')).toHaveCount(0)
  await expect(page.locator('.project-dataset-table').first()).toContainText('烟火训练集')
  await expect(page.locator('.project-dataset-row.total').first()).toContainText('合计')
  await page.locator('.project-picker-trigger').click()
  await page.getByRole('group', { name: '项目筛选' }).getByLabel('安全帽').uncheck()
  await expect(page.locator('.project-section')).toHaveCount(1)
  await expect(page.locator('.project-picker-trigger')).toContainText('所属项目：烟火检测')
  expect(queried.at(-1)).toEqual(['烟火检测'])
  await expect(page.locator('.project-file-table')).toContainText('sample.jpg')
})

test('参数管理分组展示预置指标并可维护自定义指标', async ({ page }) => {
  await mockApi(page)
  let categoryNames = ['图像分类', '目标检测', '语义分割', '实例分割', 'OCR', '姿态和关键点']
  await page.route(/\/api\/v1\/metric-categories(?:\?.*)?$/, route => {
    if (route.request().method() === 'POST') {
      const name = route.request().postDataJSON().name
      categoryNames = [...categoryNames, name]
      return json(route, {id:`category-${name}`, name, built_in:false}, 201)
    }
    return json(route, {items:categoryNames.map(name => ({id:name==='语音识别'?'category-音频识别':`category-${name}`, name, built_in:!['音频识别','语音识别'].includes(name)}))})
  })
  await page.route(/\/api\/v1\/metric-categories\/[^/?]+$/, route => {
    if (route.request().method() === 'PATCH') {
      const name = route.request().postDataJSON().name
      categoryNames = categoryNames.map(value => value === '音频识别' ? name : value)
      items = items.map(item => item.category === '音频识别' ? {...item, category:name} : item)
      return json(route, {id:`category-音频识别`, name, built_in:false})
    }
    if (route.request().method() !== 'DELETE') return json(route, {}, 405)
    categoryNames = categoryNames.filter(name => name !== '语音识别')
    return route.fulfill({status:204})
  })
  let items = [
    { id:'metric-accuracy', name:'准确率 (Accuracy)', category:'图像分类', description:'分类正确的样本比例', built_in:true },
    { id:'metric-map', name:'mAP (mean Average Precision)', category:'目标检测', description:'各类别平均精度的均值', built_in:true },
    { id:'metric-pixel_accuracy', name:'Pixel Accuracy', category:'语义分割', description:'正确分类的像素比例', built_in:true },
    { id:'metric-miou', name:'Mean Intersection over Union (mIoU)', category:'语义分割', description:'所有类别交并比的平均值', built_in:true },
    { id:'metric-dice', name:'Dice Coefficient', category:'语义分割', description:'衡量预测与真实标签的重合程度', built_in:true },
    { id:'metric-instance_map', name:'mAP (mean Average Precision)', category:'实例分割', description:'针对实例级别的预测', built_in:true },
    { id:'metric-instance_iou', name:'IoU (Intersection over Union)', category:'实例分割', description:'实例级别的交并比', built_in:true },
    { id:'metric-cer', name:'CER (Character Error Rate)', category:'OCR', description:'字符错误率', built_in:true },
    { id:'metric-wer', name:'WER (Word Error Rate)', category:'OCR', description:'单词错误率', built_in:true },
    { id:'metric-pck', name:'PCK (Percentage of Correct Keypoints)', category:'姿态和关键点', description:'关键点正确率', built_in:true },
    { id:'metric-oks', name:'OKS (Object Keypoint Similarity)', category:'姿态和关键点', description:'对象关键点相似度', built_in:true },
  ]
  const writes: Array<{method:string;body?:unknown}> = []
  await page.route(/\/api\/v1\/metric-definitions(?:\/[^/?]+)?(?:\?.*)?$/, route => {
    const request = route.request()
    const method = request.method()
    if (method === 'GET') return json(route, { items })
    const body = method === 'DELETE' ? undefined : request.postDataJSON()
    writes.push({method, body})
    if (method === 'POST') {
      const item = {id:'metric-custom', ...body, built_in:false}
      items = [...items, item]
      return json(route, item, 201)
    }
    if (method === 'PATCH') {
      items = items.map(item => item.id === 'metric-custom' ? {...item, ...body} : item)
      return json(route, items.find(item => item.id === 'metric-custom'))
    }
    items = items.filter(item => item.id !== 'metric-custom')
    return route.fulfill({status:204})
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.locator('.sidebar nav').getByRole('button', {name:/参数管理/}).click()
  await expect(page.getByRole('heading', {name:'参数管理'})).toBeVisible()
  await expect(page.getByText('此处管理指标定义，不展示或计算模型实测值。')).toHaveCount(0)
  await page.getByRole('button', {name:'分类编辑'}).click()
  const categoryDialog = page.getByRole('dialog', {name:'分类编辑'})
  await expect(categoryDialog.locator('.category-editor-row')).toHaveCount(6)
  await expect(categoryDialog.locator('.category-editor-row').first().getByRole('button', {name:'编辑'})).toHaveCount(0)
  await categoryDialog.getByRole('button', {name:'新增分类'}).click()
  await categoryDialog.getByRole('textbox', {name:'新增分类'}).fill('音频识别')
  await categoryDialog.getByRole('button', {name:'确认新增'}).click()
  await expect(categoryDialog.locator('.category-editor-row')).toHaveCount(7)
  await categoryDialog.locator('.category-editor-row').last().getByRole('button', {name:'编辑'}).click()
  await categoryDialog.getByRole('textbox', {name:'编辑分类'}).fill('语音识别')
  await categoryDialog.getByRole('button', {name:'保存修改'}).click()
  await expect(categoryDialog.locator('.category-editor-row').last()).toContainText('语音识别')
  await categoryDialog.getByRole('button', {name:'关闭', exact:true}).click()
  await expect(page.getByRole('heading', {name:'语音识别'})).toBeVisible()
  await expect(page.locator('.metric-group').last()).toContainText('暂无指标')
  await expect(page.locator('.metric-group').first().getByRole('button', {name:'删除'})).toHaveCount(0)
  await page.getByRole('button', {name:'新增指标'}).click()
  await expect(page.getByRole('dialog', {name:'新增指标'}).getByRole('combobox', {name:'分类'})).toHaveValue('图像分类')
  await expect(page.getByRole('dialog', {name:'新增指标'}).getByRole('option', {name:'语音识别'})).toHaveCount(1)
  await page.getByRole('dialog', {name:'新增指标'}).getByRole('button', {name:'取消'}).click()
  await expect(page.locator('.metric-group')).toHaveCount(7)
  await expect(page.locator('.metric-group').first()).toContainText('1 项指标')
  await expect(page.locator('.metric-group').first()).toContainText('准确率 (Accuracy)')
  const detectionGroup = page.locator('.metric-group').filter({has:page.getByRole('heading', {name:'目标检测'})})
  await expect(detectionGroup).toContainText('mAP (mean Average Precision)')
  const detectionToggle = detectionGroup.getByRole('button', {name:'目标检测'})
  await expect(detectionToggle).toHaveAttribute('aria-expanded', 'true')
  await detectionToggle.click()
  await expect(detectionToggle).toHaveAttribute('aria-expanded', 'false')
  await expect(detectionGroup.getByText('mAP (mean Average Precision)')).toHaveCount(0)
  await expect(page.locator('.metric-group').first()).toContainText('准确率 (Accuracy)')
  await detectionToggle.click()
  await expect(detectionToggle).toHaveAttribute('aria-expanded', 'true')
  await expect(detectionGroup).toContainText('mAP (mean Average Precision)')
  await expect(page.locator('.metric-group').filter({has:page.getByRole('heading', {name:'语义分割'})})).toContainText('3 项指标')
  await expect(page.locator('.metric-group').filter({has:page.getByRole('heading', {name:'实例分割'})})).toContainText('2 项指标')
  await expect(page.locator('.metric-group').filter({has:page.getByRole('heading', {name:'OCR'})})).toContainText('CER (Character Error Rate)')
  await expect(page.locator('.metric-group').filter({has:page.getByRole('heading', {name:'姿态和关键点'})})).toContainText('OKS (Object Keypoint Similarity)')
  await expect(page.locator('.metric-row').filter({hasText:'准确率 (Accuracy)'}).getByRole('button', {name:'删除'})).toHaveCount(0)

  await page.getByRole('button', {name:'新增指标'}).click()
  const dialog = page.getByRole('dialog', {name:'新增指标'})
  await dialog.getByRole('textbox', {name:'指标名称'}).fill('自定义指标')
  await dialog.getByRole('combobox', {name:'分类'}).selectOption('语音识别')
  await dialog.getByRole('textbox', {name:'描述'}).fill('自定义说明')
  await dialog.getByRole('button', {name:'保存'}).click()
  await expect(page.locator('.metric-group').last()).toContainText('1 项指标')
  await page.getByRole('button', {name:'分类编辑'}).click()
  await expect(page.getByRole('dialog', {name:'分类编辑'}).locator('.category-editor-row').last().getByRole('button', {name:'删除'})).toBeDisabled()
  await page.getByRole('dialog', {name:'分类编辑'}).getByRole('button', {name:'关闭', exact:true}).click()
  const custom = page.locator('.metric-row').filter({hasText:'自定义指标'})
  await custom.getByRole('button', {name:'编辑'}).click()
  await page.getByRole('dialog', {name:'编辑指标'}).getByRole('textbox', {name:'描述'}).fill('更新说明')
  await page.getByRole('dialog', {name:'编辑指标'}).getByRole('button', {name:'保存'}).click()
  await expect.poll(() => writes.length).toBe(2)
  await expect(custom).toContainText('更新说明')
  await custom.getByRole('button', {name:'删除'}).click()
  await expect(page.getByRole('dialog', {name:'删除指标参数'}).getByRole('button', {name:'确认删除'})).toHaveClass(/confirm-delete/)
  await page.getByRole('dialog', {name:'删除指标参数'}).getByRole('button', {name:'确认删除'}).click()
  await expect(custom).toHaveCount(0)
  await page.getByRole('button', {name:'分类编辑'}).click()
  await page.getByRole('dialog', {name:'分类编辑'}).locator('.category-editor-row').last().getByRole('button', {name:'删除'}).click()
  await page.getByRole('dialog', {name:'删除指标分类'}).getByRole('button', {name:'确认删除'}).click()
  await expect(page.getByRole('heading', {name:'语音识别'})).toHaveCount(0)
  await expect(page.locator('.metric-group')).toHaveCount(6)
  expect(writes).toEqual([
    {method:'POST', body:{name:'自定义指标', category:'语音识别', description:'自定义说明'}},
    {method:'PATCH', body:{name:'自定义指标', category:'语音识别', description:'更新说明'}},
    {method:'DELETE', body:undefined},
  ])
})

test('仅有参数菜单权限的用户只能查看指标', async ({ page }) => {
  const readOnlyTokens = {
    ...tokens,
    user: { id:'reader', username:'reader', roles:['custom'], menu_permissions:['parameters'], action_permissions:[] },
  }
  await mockApi(page, [], 0, readOnlyTokens)
  await page.route(/\/api\/v1\/metric-definitions(?:\?.*)?$/, route => json(route, {
    items:[{id:'metric-accuracy', name:'准确率 (Accuracy)', category:'图像分类', description:'分类正确的样本比例', built_in:true}],
  }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), readOnlyTokens)
  await page.goto('/')
  await expect(page.getByRole('heading', {name:'参数管理'})).toBeVisible()
  await expect(page.locator('.metric-group').first()).toContainText('准确率 (Accuracy)')
  await expect(page.getByRole('button', {name:'新增指标'})).toHaveCount(0)
  await expect(page.locator('.metric-actions')).toHaveCount(0)
})

test('项目概览在空项目和手机宽度下可用', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page)
  await page.route(/\/api\/v1\/projects\/overview(?:\?.*)?$/, route => json(route, {
    available_projects: [], selected_projects: [],
    summary: { project_count: 0, dataset_count: 0, model_count: 0, file_count: 0 },
    projects: [],
  }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /项目概览/ }).click()
  await expect(page.getByText('请先在标签管理的“项目”字段中添加项目值。')).toBeVisible()
  await expect(page.locator('.project-stat-grid article')).toHaveCount(4)
  await expect.poll(() => page.locator('.sidebar nav').evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true)
})

test('项目概览隐藏空项目和无数据模块', async ({ page }) => {
  await mockApi(page)
  const counts = { image: 0, video: 0, annotation: 0, archive: 0, other: 0 }
  await page.route(/\/api\/v1\/projects\/overview(?:\?.*)?$/, route => json(route, {
    available_projects: ['空项目', '仅有模型'], selected_projects: ['空项目', '仅有模型'],
    summary: { project_count: 2, dataset_count: 0, model_count: 1, file_count: 0 },
    projects: [
      { name: '空项目', dataset_count: 0, dataset_counts: counts, datasets: [], model_count: 0, models: [], file_count: 0, file_counts: counts, files: [], files_truncated: false },
      { name: '仅有模型', dataset_count: 0, dataset_counts: counts, datasets: [], model_count: 1, models: [{ id: 'model-1', name: 'model.pt', remark: '', sources: ['项目标签'], versions: [] }], file_count: 0, file_counts: counts, files: [], files_truncated: false },
    ],
  }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /项目概览/ }).click()
  await expect(page.locator('.project-section')).toHaveCount(1)
  await expect(page.locator('.project-section')).toContainText('仅有模型')
  await expect(page.locator('.project-module')).toHaveCount(1)
  await expect(page.getByRole('heading', { name: '模型情况' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '数据集情况' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '其他文件' })).toHaveCount(0)
})

test('项目概览进入数据集详情后返回会加载数据集列表', async ({ page }) => {
  await mockApi(page)
  let listLoads = 0
  const dataset = { id: 'dataset-1', name: '烟火训练集', remark: '', status: '待整理', projects: ['烟火检测'], member_count: 0, counts: {} }
  await page.route(/\/api\/v1\/projects\/overview(?:\?.*)?$/, route => json(route, {
    available_projects: ['烟火检测'], selected_projects: ['烟火检测'],
    summary: { project_count: 1, dataset_count: 1, model_count: 0, file_count: 0 },
    projects: [{ name: '烟火检测', dataset_count: 1, dataset_counts: { image: 0, video: 0, annotation: 0, archive: 0, other: 0 }, datasets: [{ id: dataset.id, name: dataset.name, counts: { image: 0, video: 0, annotation: 0, archive: 0, other: 0 } }], model_count: 0, models: [], file_count: 0, file_counts: {}, files: [], files_truncated: false }],
  }))
  await page.route(/\/api\/v1\/datasets(?:\/.*)?(?:\?.*)?$/, route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/creators')) return json(route, { items: [] })
    if (path.endsWith('/members') || path.endsWith('/versions') || path.endsWith('/models') || path.endsWith('/tag-distribution')) return json(route, { items: [], total: 0 })
    if (path.endsWith('/datasets')) { listLoads++; return json(route, { items: [dataset], total: 1 }) }
    return json(route, dataset)
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /项目概览/ }).click()
  await page.locator('.project-dataset-row').filter({ hasText: dataset.name }).click()
  await expect(page.locator('.dataset-detail-head')).toContainText(dataset.name)
  await page.getByRole('button', { name: /返回数据集/ }).click()
  await expect(page.locator('.dataset-table')).toContainText(dataset.name)
  expect(listLoads).toBe(1)
  await page.locator('.sidebar nav').getByRole('button', { name: /系统概览/ }).click()
  await page.getByRole('button', { name: '查看数据集' }).click()
  await expect(page.locator('.dataset-table')).toContainText(dataset.name)
  await expect(page.locator('.dataset-detail-head')).toHaveCount(0)
  expect(listLoads).toBe(2)
  await page.locator('.dataset-table').getByRole('button', { name: /烟火训练集/ }).click()
  await expect(page.locator('.dataset-detail-head')).toContainText(dataset.name)
  await page.locator('.sidebar nav').getByRole('button', { name: /数据集/ }).click()
  await expect(page.locator('.dataset-table')).toContainText(dataset.name)
  await expect(page.locator('.dataset-detail-head')).toHaveCount(0)
  expect(listLoads).toBe(3)
})

test('已有关联只能编辑备注并保持模型和版本不变', async ({ page }) => {
  await mockApi(page)
  const dataset = { id: 'dataset-1', name: '烟火训练集', remark: '', status: '待整理', projects: ['烟火检测'], member_count: 0, counts: {} }
  let remark = '原备注'
  let metricValue = '0.95'
  const patches: unknown[] = []
  await page.route(/\/api\/v1\/datasets(?:\/.*)?(?:\?.*)?$/, async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/creators')) return json(route, { items: [] })
    if (path.endsWith('/datasets')) return json(route, { items: [dataset], total: 1 })
    if (path.endsWith('/members')) return json(route, { items: [], total: 0 })
    if (path.endsWith('/tag-distribution')) return json(route, { items: [] })
    if (path.endsWith('/versions')) return json(route, { items: [{ id: 'version-1', version: 'v1', member_count: 0 }] })
    if (path.endsWith('/models')) return json(route, { items: [{ relation: { id: 'relation-1', provenance: { remark } }, model: { id: 'model-1', name: '检测模型' }, version: { id: 'version-1', version: 'v1' }, configured_parameters: metricValue ? [{id:'accuracy',name:'准确率',category:'图像分类',value:metricValue}] : [] }] })
    if (path.endsWith('/models/relation-1') && route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      patches.push(body)
      remark = body.remark
      return json(route, { relation: { id: 'relation-1', provenance: { remark } } })
    }
    return json(route, dataset)
  })
  await page.route(/\/api\/v1\/assets\/model-1\/parameters$/, route => {
    if (route.request().method() === 'PATCH') metricValue = route.request().postDataJSON().values.accuracy || ''
    return json(route, {asset_id:'model-1',items:[{id:'accuracy',name:'准确率',category:'图像分类',description:'分类正确的样本比例',value:metricValue||null}]})
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.locator('.sidebar nav').getByRole('button', { name: /数据集/ }).click()
  await page.locator('.dataset-table').getByRole('button', { name: /烟火训练集/ }).click()
  await page.getByRole('button', { name: '模型管理' }).click()
  await expect(page.locator('.dataset-models article')).toContainText('关联数据集版本：v1')
  await expect(page.locator('.dataset-models article')).not.toContainText('由v1版本数据集训练')
  await expect(page.locator('.dataset-models article .model-summary')).toContainText('准确率：0.95')
  await expect(page.locator('.dataset-models article .model-summary .model-version')).toHaveText('关联数据集版本：v1')
  await expect(page.locator('.model-relation-actions button')).toHaveText(['编辑参数', '编辑备注', '删除关联'])
  await page.getByRole('button', {name:'编辑参数'}).click()
  const parametersDialog = page.getByRole('dialog', {name:'参数配置'})
  await expect(parametersDialog.getByRole('textbox', {name:'准确率'})).toHaveValue('0.95')
  await parametersDialog.getByRole('textbox', {name:'准确率'}).fill('0.98')
  await parametersDialog.getByRole('button', {name:'保存参数'}).click()
  await expect(page.locator('.dataset-models article .model-summary')).toContainText('准确率：0.98')
  await page.getByRole('button', { name: '编辑备注' }).click()
  const dialog = page.getByRole('dialog', { name: '编辑关联备注' })
  await expect(dialog).toContainText('检测模型 · v1')
  await expect(dialog.locator('select')).toHaveCount(0)
  await dialog.getByRole('textbox', { name: '备注' }).fill('修订备注')
  await dialog.getByRole('button', { name: '保存备注' }).click()
  await expect(page.locator('.dataset-models article')).toContainText('修订备注')
  await expect(page.locator('.dataset-models article')).toContainText('v1')
  await page.getByRole('button', { name: '编辑备注' }).click()
  await page.getByRole('dialog', { name: '编辑关联备注' }).getByRole('textbox', {name:'备注'}).fill('')
  await page.getByRole('dialog', { name: '编辑关联备注' }).getByRole('button', {name:'保存备注'}).click()
  await expect(page.locator('.dataset-models article .model-summary>span')).toHaveCount(0)
  expect(patches).toEqual([{ remark: '修订备注' }, { remark: '' }])
})

test('添加模型关联时按模型备注自动填写且空备注不覆盖手动输入', async ({ page }) => {
  await mockApi(page)
  const dataset = { id: 'dataset-1', name: '烟火训练集', remark: '', status: '待整理', projects: ['烟火检测'], member_count: 0, counts: {} }
  await page.route(/\/api\/v1\/datasets(?:\/.*)?(?:\?.*)?$/, route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/creators')) return json(route, { items: [] })
    if (path.endsWith('/datasets')) return json(route, { items: [dataset], total: 1 })
    if (path.endsWith('/members')) return json(route, { items: [], total: 0 })
    if (path.endsWith('/tag-distribution')) return json(route, { items: [] })
    if (path.endsWith('/versions')) return json(route, { items: [{ id: 'version-1', version: 'v1', member_count: 0 }] })
    if (path.endsWith('/models')) return json(route, { items: [] })
    return json(route, dataset)
  })
  await page.route(/\/api\/v1\/assets(?:\?.*)?$/, route => {
    const params = new URL(route.request().url()).searchParams
    if (params.get('asset_type') !== 'model') return route.fallback()
    if (params.get('page') === '1') return json(route, {items:Array.from({length:200},(_,i)=>({id:`filler-${i}`,name:`模型 ${i}`,type:'model',remark:''})),total:202})
    return json(route, { items: [
      { id: 'model-1', name: '有备注模型', type: 'model', remark: '模型原备注' },
      { id: 'model-2', name: '无备注模型', type: 'model', remark: '' },
    ], total: 202 })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.locator('.sidebar nav').getByRole('button', { name: /数据集/ }).click()
  await page.locator('.dataset-table').getByRole('button', { name: /烟火训练集/ }).click()
  await page.getByRole('button', { name: '模型管理' }).click()
  await page.getByRole('button', { name: /添加模型关联/ }).click()
  const dialog = page.getByRole('heading', { name: '添加模型关联' }).locator('..')
  const modelSelect = dialog.getByLabel('模型')
  const remark = dialog.getByRole('textbox', { name: '备注' })
  await modelSelect.selectOption('model-1')
  await expect(remark).toHaveValue('模型原备注')
  await modelSelect.selectOption('model-2')
  await expect(remark).toHaveValue('')
  await modelSelect.selectOption('model-1')
  await remark.fill('手动关联备注')
  await modelSelect.selectOption('model-2')
  await expect(remark).toHaveValue('手动关联备注')
})

test('数据集详情响应延迟时返回列表不会被旧响应覆盖', async ({ page }) => {
  await mockApi(page)
  const dataset = { id: 'dataset-1', name: '烟火训练集', remark: '', status: '待整理', projects: ['烟火检测'], member_count: 0, counts: {} }
  let releaseDetail: (() => void) | undefined
  let detailRequested: (() => void) | undefined
  const requested = new Promise<void>(resolve => { detailRequested = resolve })
  const gate = new Promise<void>(resolve => { releaseDetail = resolve })
  await page.route(/\/api\/v1\/projects\/overview(?:\?.*)?$/, route => json(route, {
    available_projects: ['烟火检测'], selected_projects: ['烟火检测'],
    summary: { project_count: 1, dataset_count: 1, model_count: 0, file_count: 0 },
    projects: [{ name: '烟火检测', dataset_count: 1, dataset_counts: {}, datasets: [{ id: dataset.id, name: dataset.name, counts: {} }], model_count: 0, models: [], file_count: 0, file_counts: {}, files: [], files_truncated: false }],
  }))
  await page.route(/\/api\/v1\/datasets(?:\/.*)?(?:\?.*)?$/, async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/creators')) return json(route, { items: [] })
    if (path.endsWith('/datasets')) return json(route, { items: [dataset], total: 1 })
    if (path.endsWith('/datasets/dataset-1')) { detailRequested?.(); await gate; return json(route, dataset) }
    return json(route, { items: [], total: 0 })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /项目概览/ }).click()
  await page.locator('.project-dataset-row').filter({ hasText: dataset.name }).click()
  await requested
  await page.locator('.sidebar nav').getByRole('button', { name: /数据集/ }).click()
  await expect(page.locator('.dataset-table')).toContainText(dataset.name)
  releaseDetail?.()
  await page.waitForTimeout(100)
  await expect(page.locator('.dataset-detail-head')).toHaveCount(0)
})

test('桌面和手机宽度下主要页面可切换且不产生整页横向溢出', async ({ page }) => {
  test.setTimeout(90000)
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  const permissionsLoaded = page.waitForResponse('**/api/v1/permissions/me')
  await page.goto('/')
  await permissionsLoaded
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 844 })
    const menus = page.locator('.sidebar nav button')
    for (let index = 0; index < await menus.count(); index++) {
      await menus.nth(index).click()
      await expect(page.locator('main')).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `菜单 ${index + 1} 在 ${width}px 宽度下横向溢出`).toBeLessThanOrEqual(1)
    }
  }
})

test('标签与格式管理页保持独立展示和操作入口', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/v1/tag-definitions', route => json(route, { items: [{ key: 'scene', name: '场景', color: '#123456', values: ['室内'], built_in: false }] }))
  await page.route('**/api/v1/format-definitions', route => json(route, { items: [{ asset_type: 'image', extensions: ['.jpg'], remark: '图像', built_in: false }] }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: '标签管理' }).click()
  await expect(page.locator('.tag-admin')).toContainText('室内')
  await expect(page.getByRole('button', { name: '新建标签字段' })).toBeVisible()
  await page.getByRole('button', { name: '格式管理' }).click()
  await expect(page.locator('.tag-admin')).toContainText('.jpg')
  await expect(page.getByRole('button', { name: '新增格式' })).toBeVisible()
})

test('数据集所属项目必选、支持多选并跳转到项目修改弹窗', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/v1/tag-definitions', route => json(route, { items: [
    { key: 'project', name: '项目', values: ['烟火检测', '安全帽'], color: '#2764c6', built_in: true },
    { key: 'status', name: '状态', values: ['待整理'], built_in: true },
  ] }))
  await page.route('**/api/v1/datasets', route => json(route, { items: [], total: 0 }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /数据集/ }).first().click()
  await page.getByRole('button', { name: /新建数据集/ }).first().click()
  const dialog = page.locator('.dataset-dialog').first()
  await dialog.getByPlaceholder('请输入名称').fill('测试数据集')
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  await dialog.getByRole('group', { name: '所属项目' }).getByLabel('烟火检测').check()
  await dialog.getByRole('group', { name: '所属项目' }).getByLabel('安全帽').check()
  await expect(dialog.getByRole('group', { name: '所属算法' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeEnabled()
  await dialog.getByRole('button', { name: '新增项目' }).click()
  await expect(page.getByRole('heading', { name: '标签管理' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '修改标签字段' })).toBeVisible()
  await expect(page.locator('.tag-dialog input[placeholder="例如 weather"]')).toHaveValue('project')
  await page.locator('.tag-dialog .close').click()
  await page.getByRole('button', { name: /数据集/ }).first().click()
  await expect(page.locator('.dataset-dialog').getByPlaceholder('请输入名称')).toHaveValue('测试数据集')
  await expect(page.locator('.dataset-dialog').getByRole('group', { name: '所属项目' }).getByLabel('安全帽')).toBeChecked()
})

test('数据集新增和编辑均保存所属项目', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/v1/tag-definitions', route => json(route, { items: [
    { key: 'project', name: '项目', values: ['烟火检测', '安全帽'], built_in: true },
    { key: 'status', name: '状态', values: ['待整理'], built_in: true },
  ] }))
  let created: any = null
  let updated: any = null
  await page.route(/\/api\/v1\/datasets(?:\/.*)?(?:\?.*)?$/, route => {
    const path = new URL(route.request().url()).pathname
    const dataset = { id: 'dataset-1', name: '测试数据集', remark: '', status: '待整理', projects: updated?.projects || created?.projects || [], member_count: 0, counts: {} }
    if (path.endsWith('/creators')) return json(route, { items: [] })
    if (path.endsWith('/members') || path.endsWith('/versions') || path.endsWith('/models') || path.endsWith('/tag-distribution')) return json(route, { items: [], total: 0 })
    if (route.request().method() === 'POST') { created = route.request().postDataJSON(); return json(route, { ...dataset, projects: created.projects }, 201) }
    if (route.request().method() === 'PATCH') { updated = route.request().postDataJSON(); return json(route, { ...dataset, ...updated }) }
    if (path.endsWith('/datasets')) return json(route, { items: [], total: 0 })
    return json(route, dataset)
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /数据集/ }).first().click()
  await page.getByRole('button', { name: /新建数据集/ }).first().click()
  const dialog = page.locator('.dataset-dialog').first()
  await dialog.getByPlaceholder('请输入名称').fill('测试数据集')
  await dialog.getByRole('group', { name: '所属项目' }).getByLabel('烟火检测').check()
  await dialog.getByRole('group', { name: '所属项目' }).getByLabel('安全帽').check()
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => created?.projects).toEqual(['烟火检测', '安全帽'])
  expect(created).not.toHaveProperty('algorithms')
  await page.locator('.dataset-detail-actions').getByRole('button', { name: '编辑' }).click()
  await expect(dialog.getByRole('group', { name: '所属项目' }).getByLabel('烟火检测')).toBeChecked()
  await dialog.getByRole('group', { name: '所属项目' }).getByLabel('安全帽').uncheck()
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => updated?.projects).toEqual(['烟火检测'])
  expect(updated).not.toHaveProperty('algorithms')
})

test('回收站独立页面可选择、翻页并确认还原', async ({ page }) => {
  await mockApi(page)
  await page.route('**/api/v1/permissions/me', route => json(route, {
    role: 'admin', menus: ['overview', 'library', 'trash'].map(key => ({ key, name: key })),
    actions: [{ key: 'trash_manage', name: '管理回收站' }],
  }))
  const requests: number[] = []
  await page.route('**/api/v1/assets/trash/items**', route => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get('page') || 1)
    requests.push(pageNumber)
    return json(route, { items: [{ id: `trash-${pageNumber}`, name: `已删除素材 ${pageNumber}.jpg`, type: 'image', status: 'deleted', size: 1024, tags: {}, created_at: '2026-10-01T00:00:00Z' }], total: 51 })
  })
  let restored: unknown = null
  await page.route('**/api/v1/assets/trash/restore', async route => {
    restored = route.request().postDataJSON()
    return json(route, { succeeded: ['trash-2'], failed: [] })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /回收站/ }).click()
  await expect(page.getByRole('heading', { name: '回收站' })).toBeVisible()
  await expect(page.locator('.trash-shell')).toContainText('已删除素材 1.jpg')
  await page.locator('.trash-shell .pagination button').last().click()
  await expect(page.locator('.trash-shell')).toContainText('已删除素材 2.jpg')
  expect(requests).toEqual([1, 2])
  await page.getByRole('button', { name: '选择 已删除素材 2.jpg' }).click()
  await page.locator('.page-head').getByRole('button', { name: '还原' }).click()
  await expect(page.getByText('确定要还原1项吗？')).toBeVisible()
  await page.getByRole('button', { name: '确认还原', exact: true }).click()
  await expect.poll(() => restored).toEqual({ asset_ids: ['trash-2'] })
})

test('登录后才加载系统概览', async ({ page }) => {
  let loads = 0
  await mockApi(page)
  await page.route('**/api/v1/system/overview', route => {
    loads++
    return json(route, { counts: { assets: 6 }, asset_types: {}, recent_activity: [] })
  })
  await page.goto('/')
  expect(loads).toBe(0)
  await page.getByLabel('用户名', { exact: true }).fill('admin')
  await page.getByLabel('密码', { exact: true }).fill('admin')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.locator('.overview-cards')).toContainText('6')
  expect(loads).toBe(1)
})

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
      const custom = role === 'custom'
      return json(route, {
        role,
        menus: (custom
          ? ((sessionTokens.user as any).menu_permissions || [])
          : annotator
          ? ['library', 'datasets', 'relations', 'lineage', 'downloads']
          : ['overview', 'project_overview', 'library', 'datasets', 'relations', 'lineage', 'downloads', 'tags', 'formats', 'parameters', 'admin', 'roles', 'logs']
        ).map(key => ({ key, name: key })),
        actions: (custom
          ? ((sessionTokens.user as any).action_permissions || [])
          : annotator
          ? ['asset_upload', 'asset_edit', 'saved_view_manage', 'dataset_create_edit', 'dataset_members_manage', 'dataset_version_publish', 'relation_manage', 'export_create']
          : ['asset_upload', 'asset_edit', 'asset_delete', 'saved_view_manage', 'dataset_create_edit', 'dataset_members_manage', 'dataset_version_publish', 'dataset_version_restore', 'dataset_delete', 'dataset_model_manage', 'relation_manage', 'relation_revoke', 'export_create', 'trash_manage', 'tag_manage', 'format_manage', 'parameter_manage', 'user_manage', 'role_manage']
        ).map(key => ({ key, name: key })),
      })
    }
    if (path.endsWith('/users')) return json(route, { items: [] })
    if (path.endsWith('/role-templates/role-1') && request.method() === 'DELETE') return json(route, { error: { code: 'ROLE_IN_USE', message: '已有用户zhangsan绑定该角色，不可删除' } }, 409)
    if (path.endsWith('/role-templates/role-1') && request.method() === 'PUT') return json(route, { id: 'role-1', name: '质检角色' })
    if (path.endsWith('/role-impact/role-1')) return json(route, {
      affected_count: 2, active_count: 1, disabled_count: 1, users_truncated: false,
      users: [{ username: 'zhangsan', status: 'active' }, { username: 'lisi', status: 'disabled' }],
      usernames: ['zhangsan', 'lisi'], menus_added: ['datasets'], menus_removed: [],
      actions_added: ['dataset_create_edit'], actions_removed: ['asset_edit'],
    })
    if (path.endsWith('/roles')) {
      const menus = [
        ['project_overview', '项目概览'], ['library', '素材库'], ['datasets', '数据集管理'], ['relations', '关联关系'], ['lineage', '模型溯源'],
        ['downloads', '任务中心'], ['trash', '回收站'], ['tags', '标签管理'], ['formats', '格式管理'], ['parameters', '参数管理'],
        ['admin', '用户管理'], ['roles', '角色管理'], ['logs', '系统日志'],
      ].map(([key, name]) => ({ key, name }))
      const actions = [
        ['asset_upload', '上传素材', 'library'], ['asset_edit', '编辑素材', 'library'], ['asset_delete', '删除素材', 'library'],
        ['saved_view_manage', '管理保存视图', 'library'], ['dataset_create_edit', '创建编辑数据集', 'datasets'],
        ['dataset_members_manage', '管理数据集成员', 'datasets'], ['dataset_version_publish', '发布数据集版本', 'datasets'],
        ['dataset_version_restore', '恢复数据集版本', 'datasets'], ['dataset_delete', '删除数据集', 'datasets'],
        ['dataset_model_manage', '管理模型关联', 'relations'], ['relation_manage', '管理关联关系', 'relations'],
        ['relation_revoke', '撤销关联关系', 'relations'], ['export_create', '创建导出', 'downloads'],
        ['trash_manage', '管理回收站', 'trash'], ['tag_manage', '管理标签', 'tags'],
        ['format_manage', '管理格式', 'formats'], ['parameter_manage', '管理模型指标参数', 'parameters'], ['user_manage', '管理用户', 'admin'], ['role_manage', '管理角色', 'roles'],
      ].map(([key, name, menu]) => ({ key, name, menu }))
      return json(route, {
        items: [{ key: 'admin', name: '管理员', built_in: true, menu_permissions: menus.map(item => item.key), action_permissions: actions.map(item => item.key) }, { key: 'data_manager', name: '数据管理员', built_in: false, menu_permissions: ['overview','library','datasets'], action_permissions: ['asset_edit'] }],
        menus,
        actions,
        templates: [{ id: 'role-1', name: '质检角色', built_in: false, menu_permissions: ['overview','library'], action_permissions: ['asset_edit'] }],
      })
    }
    if (path.endsWith('/assets/stats')) return json(route, { total: assetRows.length, untagged: assetRows.length, by_type: { other: assetRows.length }, storage: { total: 0, used: 0, free: 0 } })
    if (path.endsWith('/metric-categories')) return json(route, { items: ['图像分类', '目标检测', '语义分割', '实例分割', 'OCR', '姿态和关键点'].map(name => ({id:`category-${name}`, name, built_in:true})) })
    if (path.endsWith('/metric-definitions')) return json(route, { items: [] })
    if (path.endsWith('/system/health')) return json(route, { status: 'ok', checks: { mongodb: true, minio: true, redis: true } })
    if (path.endsWith('/system/overview')) return json(route, { counts: { assets: assetRows.length, datasets: 2, relations: 3, running_jobs: 1, failed_jobs: 0 }, asset_types: { image: assetRows.length }, recent_activity: [] })
    if (path.endsWith('/system/search')) return json(route, { query: '示例', groups: [{ type: 'asset', label: '素材', total: 12, items: [{ id: 'asset-1', name: '示例素材.jpg', type: 'image', remark: '全局结果' }] }] })
    if (path.endsWith('/audit-logs')) return json(route, { items: [{ id: 'audit-1', actor_id: 'admin', actor_username: 'admin', action: 'user.updated', object_type: 'user', object_id: 'user-1', object_name: '测试用户', changes: { status: 'active', roles: ['viewer'], password_changed: false, size: 1048576 }, outcome: 'success', response_status: 200, client_ip: '127.0.0.1', request_id: 'request-1', created_at: '2026-10-08T01:00:00Z' }], page: 1, page_size: 50, total: 1 })
    if (path.endsWith('/assets/upload-sessions') && request.method() === 'GET') return json(route, { items: [] })
    if (path.endsWith('/assets/trash/items')) return json(route, { items: [], total: 0 })
    if (path.endsWith('/format-definitions')) return json(route, { items: [{ asset_type: 'image', extensions: ['.jpg'] }] })
    if (path.endsWith('/saved-views') || path.endsWith('/tag-definitions')) return json(route, { items: [] })
    if (path.endsWith('/assets/upload-conflicts')) return json(route, {
      total: 1,
      groups: [{ asset_type: 'image', count: 1, items: [{ id: 'old-image', name: 'same.jpg', type: 'image', size: 1024, tags: {}, media: {}, has_active_relations: true }] }],
      items: [{ index: 0, filename: 'same.jpg', asset_type: 'image', existing_count: 1, overwrite_target_id: 'old-image', has_active_relations: true }],
    })
    if (path.endsWith('/assets/usage-impact')) return json(route, {
      total: 1, affected_count: 1, details_truncated: false,
      items: [{ id: 'old-image', name: 'same.jpg', type: 'image', relation_count: 0, other_relation_count: 0,
        current_datasets: [{ id: 'dataset-1', name: '烟火数据集' }],
        historical_versions: [{ id: 'version-1', version: 'v1', dataset_id: 'dataset-1', dataset_name: '烟火数据集' }],
        models: [{ id: 'model-1', name: '检测模型' }] }],
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
  await page.getByRole('button', { name: /素材库/ }).click()

  await page.locator('.check-list').getByRole('button', { name: /图片/ }).click()

  await expect(page.locator('.content-panel .toolbar').getByText(/当前页/)).toContainText(
    '当前页 50 项 · 全部 100 项',
  )
})

test('素材详情延迟响应不能覆盖下一项或重新打开已关闭详情', async ({ page }) => {
  const assets = ['a','b'].map(id=>({id,name:`${id}.txt`,type:'other',size:12,status:'ready',tags:{},media:{},remark:id}))
  await mockApi(page, assets)
  let release!:()=>void
  let gate = new Promise<void>(resolve=>{release=resolve})
  await page.route('**/api/v1/assets/a',async route=>{await gate;await json(route,assets[0])})
  await page.addInitScript(value=>localStorage.setItem('cv-archive-session',JSON.stringify(value)),tokens)
  await page.goto('/')
  await page.getByRole('button',{name:/素材库/}).click()
  await page.locator('.asset-card').first().locator('.asset-preview').click()
  await page.getByRole('button',{name:'下一项素材'}).click()
  await expect(page.locator('.detail-sheet h2')).toHaveText('b.txt')
  const firstResponse=page.waitForResponse('**/api/v1/assets/a')
  release();await firstResponse;await page.waitForTimeout(100)
  await expect(page.locator('.detail-sheet h2')).toHaveText('b.txt')
  await expect(page.locator('.detail-sheet textarea')).toHaveValue('b')
  gate=new Promise<void>(resolve=>{release=resolve})
  await page.getByRole('button',{name:'上一项素材'}).click()
  await page.locator('.detail-sheet .close').click()
  const closedResponse=page.waitForResponse('**/api/v1/assets/a')
  release();await closedResponse;await page.waitForTimeout(100)
  await expect(page.locator('.detail-sheet')).toHaveCount(0)
})

test('单选长项目名在手机宽度不撑宽页面', async ({page})=>{
  await mockApi(page)
  const name='P'.repeat(100)
  await page.route(/\/api\/v1\/projects\/overview(?:\?.*)?$/,route=>json(route,{available_projects:[name],selected_projects:[name],summary:{project_count:1,dataset_count:0,model_count:0,file_count:0},projects:[]}))
  await page.setViewportSize({width:390,height:844})
  await page.addInitScript(value=>localStorage.setItem('cv-archive-session',JSON.stringify(value)),tokens)
  await page.goto('/')
  await page.getByRole('button',{name:/项目概览/}).click()
  await expect(page.locator('.project-picker-label')).toHaveAttribute('title',name)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.locator('.project-picker-trigger').click()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('操作历史展示全部加载超过一百条的记录',async({page})=>{
  const asset={id:'history-asset',name:'history.txt',type:'other',size:12,status:'ready',tags:{},media:{}}
  await mockApi(page,[asset])
  const rows=Array.from({length:205},(_,i)=>({id:String(i),action:'asset.updated',actor_username:'admin',created_at:'2026-10-22T00:00:00Z'}))
  const pages:number[]=[]
  await page.route(/\/assets\/history-asset\/history(?:\?.*)?$/,route=>{
    const current=Number(new URL(route.request().url()).searchParams.get('page')||1);pages.push(current)
    return json(route,{items:rows.slice((current-1)*100,current*100),total:205,page:current,page_size:100})
  })
  await page.addInitScript(value=>localStorage.setItem('cv-archive-session',JSON.stringify(value)),tokens)
  await page.goto('/')
  await page.getByRole('button',{name:/素材库/}).click()
  await page.locator('.asset-preview').first().click()
  const history=page.locator('.operation-history')
  await expect(history.locator('li')).toHaveCount(3)
  await history.getByRole('button',{name:'展示全部'}).click()
  await expect(history.locator('li')).toHaveCount(205)
  expect(pages).toEqual([1,2,3])
  await history.getByRole('button',{name:'收起'}).click()
  await expect(history.locator('li')).toHaveCount(3)
})

test('素材详情支持方向键切换且编辑备注时不会误切换', async ({ page }) => {
  const assetRows = [
    { id: 'asset-1', name: '第一项.txt', type: 'other', size: 12, status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T01:00:00Z' },
    { id: 'asset-2', name: '第二项.txt', type: 'other', size: 24, status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T02:00:00Z' },
  ]
  await mockApi(page, assetRows)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /素材库/ }).click()
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

test('素材操作历史默认三条并可展开和收起，切换素材后恢复折叠', async ({ page }) => {
  const assets = [
    { id: 'asset-1', name: '第一项.txt', type: 'other', size: 12, status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T01:00:00Z' },
    { id: 'asset-2', name: '第二项.txt', type: 'other', size: 24, status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T02:00:00Z' },
  ]
  await mockApi(page, assets)
  await page.route(/\/api\/v1\/assets\/asset-[12]\/history$/, route => json(route, {
    items: Array.from({ length: 5 }, (_, index) => ({
      id: `history-${index}`, action: 'asset.updated', actor_username: `用户${index + 1}`,
      created_at: `2026-10-02T0${index + 1}:00:00Z`,
    })),
  }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /素材库/ }).click()
  await page.locator('.asset-card').first().locator('.asset-preview').click()
  const history = page.locator('.detail-sheet .operation-history')
  await expect(history.locator('li')).toHaveCount(3)
  await expect(history.getByRole('button', { name: '展示全部' })).toHaveAttribute('aria-expanded', 'false')
  await history.getByRole('button', { name: '展示全部' }).click()
  await expect(history.locator('li')).toHaveCount(5)
  await history.getByRole('button', { name: '收起' }).click()
  await expect(history.locator('li')).toHaveCount(3)
  await history.getByRole('button', { name: '展示全部' }).click()
  await page.getByRole('button', { name: '下一项素材' }).click()
  await expect(history.locator('li')).toHaveCount(3)
})

test('模型详情可配置独立参数并显示未配置', async ({ page }) => {
  const models = [
    { id:'model-1', name:'模型一.onnx', type:'model', size:1024, status:'ready', tags:{}, media:{}, created_at:'2026-10-02T01:00:00Z' },
    { id:'model-2', name:'模型二.onnx', type:'model', size:1024, status:'ready', tags:{}, media:{}, created_at:'2026-10-02T02:00:00Z' },
  ]
  await mockApi(page, models)
  const values:Record<string,Record<string,string|null>> = {'model-1':{}, 'model-2':{accuracy:'0.81'}}
  await page.route(/\/api\/v1\/assets\/model-[12]\/parameters$/, route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-2)!
    if (route.request().method() === 'PATCH') values[id] = route.request().postDataJSON().values
    return json(route, {asset_id:id, items:[
      {id:'accuracy',name:'准确率 (Accuracy)',category:'图像分类',description:'分类正确的样本比例',value:values[id].accuracy || null},
      {id:'map',name:'mAP',category:'目标检测',description:'平均精度',value:values[id].map || null},
    ]})
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', {name:/素材库/}).click()
  await page.locator('.asset-card').filter({hasText:'模型一.onnx'}).locator('.asset-preview').click()
  const detail = page.locator('.detail-sheet')
  await expect(detail.locator('.detail-actions button')).toHaveText(['参数配置', '查看模型溯源'])
  await detail.getByRole('button', {name:'参数配置'}).click()
  const dialog = page.getByRole('dialog', {name:'参数配置'})
  await expect(dialog.getByRole('textbox', {name:'准确率 (Accuracy)'})).toHaveAttribute('placeholder', '未配置')
  await expect(dialog.getByRole('textbox', {name:'准确率 (Accuracy)'})).toHaveValue('')
  await dialog.getByRole('textbox', {name:'准确率 (Accuracy)'}).fill('0.95')
  await dialog.getByRole('button', {name:'保存参数'}).click()
  await expect(dialog).toHaveCount(0)
  await detail.getByRole('button', {name:'参数配置'}).click()
  await expect(page.getByRole('dialog', {name:'参数配置'}).getByRole('textbox', {name:'准确率 (Accuracy)'})).toHaveValue('0.95')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', {name:'参数配置'})).toHaveCount(0)
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('button', {name:'参数配置'})).toBeVisible()
  await detail.getByRole('button', {name:'参数配置'}).click()
  await page.getByRole('dialog', {name:'参数配置'}).getByRole('button', {name:'取消'}).click()
  await expect(detail.getByRole('button', {name:'查看模型溯源'})).toBeVisible()
  await page.locator('.detail-sheet-stage').click({position:{x:20,y:20}})
  await page.locator('.asset-card').filter({hasText:'模型二.onnx'}).locator('.asset-preview').click()
  await page.locator('.detail-sheet').getByRole('button', {name:'参数配置'}).click()
  await expect(page.getByRole('dialog', {name:'参数配置'}).getByRole('textbox', {name:'准确率 (Accuracy)'})).toHaveValue('0.81')
  expect(values['model-1'].accuracy).toBe('0.95')
})

test('素材详情关联数量可跳转并按素材 ID 精确筛选，零关系不可点击', async ({ page }) => {
  const assets = [
    {id:'asset-1',name:'同名素材.jpg',type:'image',size:100,status:'ready',tags:{},media:{},created_at:'2026-10-02T01:00:00Z'},
    {id:'asset-2',name:'空关系.jpg',type:'image',size:100,status:'ready',tags:{},media:{},created_at:'2026-10-02T02:00:00Z'},
  ]
  await mockApi(page, assets)
  await page.route(/\/api\/v1\/assets\/asset-[12]$/, route => {
    const asset = assets.find(item => route.request().url().endsWith(item.id))!
    return json(route, {...asset, relations:asset.id==='asset-1'?[{id:'relation-1',source_id:'asset-1',target_id:'annotation-1',status:'active',relation_type:'annotates'}]:[]})
  })
  const relationRequests:string[] = []
  await page.route(/\/api\/v1\/relations\?/, route => {
    relationRequests.push(route.request().url())
    return json(route, {items:[],total:0})
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', {name:/素材库/}).click()
  await page.locator('.asset-card').filter({hasText:'空关系.jpg'}).locator('.asset-preview').click()
  await expect(page.locator('.relation-mini')).toContainText('当前有效关系 0')
  await expect(page.locator('.relation-mini button')).toHaveCount(0)
  await page.locator('.detail-sheet-stage').click({position:{x:20,y:20}})
  await page.locator('.asset-card').filter({hasText:'同名素材.jpg'}).locator('.asset-preview').click()
  const relationSummary = page.locator('.relation-mini')
  const count = relationSummary.getByRole('button', {name:'查看 同名素材.jpg 的 1 条关联关系'})
  await expect(count).toBeVisible()
  await expect.poll(() => relationSummary.locator('p').evaluate(element => getComputedStyle(element).justifyContent)).toBe('flex-start')
  await count.click()
  await expect(page.getByRole('heading', {name:'关联关系',exact:true})).toBeVisible()
  await expect(page.getByPlaceholder('搜索素材名称或备注')).toHaveValue('同名素材.jpg')
  await expect(page.locator('.relation-history-filters select').nth(1)).toHaveValue('active')
  await expect.poll(() => relationRequests.at(-1) || '').toContain('asset_id=asset-1')
  await page.getByPlaceholder('搜索素材名称或备注').fill('其他名称')
  await page.locator('.relation-history-filters').getByRole('button', {name:'筛选'}).click()
  await expect.poll(() => relationRequests.at(-1) || '').toContain('q=%E5%85%B6%E4%BB%96%E5%90%8D%E7%A7%B0')
  expect(relationRequests.at(-1)).not.toContain('asset_id=')
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
  await page.getByRole('button', { name: /素材库/ }).click()
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
  await page.getByRole('button', { name: /素材库/ }).click()
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
  await expect(page.getByText('存在共1项同名或内容重复文件，请选择：')).toBeVisible()
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
  await expect(page.getByText(/覆盖原文件会保留素材 ID 和关联关系/)).toBeVisible()
  await expect(page.getByLabel('素材使用影响')).toContainText('关联数据集：烟火数据集')
  await expect(page.getByLabel('素材使用影响')).toContainText('关联版本：烟火数据集 v1')
  await expect(page.getByLabel('素材使用影响')).toContainText('关联模型：检测模型')
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
  await page.getByRole('button', { name: '转入后台', exact: true }).click()
  await expect(page.locator('.upload-background-status')).toContainText('后台上传 0 / 1')
  await page.locator('.upload-background-status').click()
  await expect(uploadDialog).toBeVisible()
})

test('删除素材前展示数据集、历史版本和模型引用', async ({ page }) => {
  let deleteCalls = 0
  await mockApi(page, [{ id: 'old-image', name: 'same.jpg', type: 'image', size: 1024,
    status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T01:00:00Z' }])
  await page.route('**/api/v1/assets/batch-delete', async route => {
    deleteCalls++
    expect(route.request().postDataJSON().confirm_linked).toBe(true)
    await json(route, { succeeded: ['old-image'], succeeded_count: 1, failed: [], failed_count: 0,
      details: [], details_truncated: false })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /素材库/ }).click()
  await page.getByRole('button', { name: '✓ 全选' }).click()
  await page.locator('.batch-bar').getByRole('button', { name: '删除', exact: true }).click()
  const impact = page.getByLabel('素材使用影响')
  await expect(page.locator('.confirm-dialog')).toContainText('确定要删除1项吗？其中共1项存在关联关系。')
  await expect(impact).toContainText('使用影响：存在 1 项关联关系')
  await expect(impact).toContainText('关联数据集：烟火数据集')
  await expect(impact).toContainText('关联版本：烟火数据集 v1')
  await expect(impact).toContainText('关联模型：检测模型')
  await page.locator('.confirm-dialog').getByRole('button', { name: '确认删除' }).click()
  await expect(page.locator('.confirm-dialog')).toContainText('被删除素材的关联关系会一并清除，确认继续吗？')
  expect(deleteCalls).toBe(0)
  await page.locator('.confirm-dialog').getByRole('button', { name: '确认', exact: true }).click()
  await expect.poll(() => deleteCalls).toBe(1)
  await expect(page.locator('.confirm-dialog')).toHaveCount(0)
})

test('素材库表格模式隐藏卡片密度选项', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /素材库/ }).click()
  await expect(page.getByRole('button', { name: '紧凑', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '舒适', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '表格', exact: true }).click()
  await expect(page.getByRole('button', { name: '紧凑', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '舒适', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '卡片', exact: true }).click()
  await expect(page.getByRole('button', { name: '紧凑', exact: true })).toBeVisible()
})

test('批量添加标签读取最新标签值且只能选择已有值', async ({ page }) => {
  const asset = { id: 'asset-1', name: '测试图片.jpg', type: 'image', size: 1024, status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T01:00:00Z' }
  await mockApi(page, [asset])
  let values = ['旧标签值']
  let tagLoads = 0
  let submitted = 0
  await page.route('**/api/v1/tag-definitions', route => {
    tagLoads++
    return json(route, { items: [{ key: 'scene', name: '场景', values, free_input: true }] })
  })
  await page.route('**/api/v1/assets/batch-tags', route => { submitted++; return json(route, { succeeded: ['asset-1'], failed: [] }) })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /素材库/ }).click()
  await page.getByLabel('选择 测试图片.jpg').click()
  values = ['新标签值']
  const previousLoads = tagLoads
  await page.locator('.batch-bar').getByRole('button', { name: '添加标签' }).click()
  const dialog = page.locator('.compact-dialog').filter({ hasText: '为 1 项素材添加标签' })
  await expect.poll(() => tagLoads).toBeGreaterThan(previousLoads)
  await expect(dialog.getByLabel('标签值').locator('option')).toContainText(['请选择', '新标签值'])
  await expect(dialog.getByLabel('标签值').locator('option', { hasText: '旧标签值' })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: '输入自定义值' })).toHaveCount(0)
  await expect(dialog.locator('input[placeholder="请输入标签值"]')).toHaveCount(0)
  await dialog.getByLabel('标签值').selectOption('新标签值')
  await expect(dialog.getByRole('button', { name: '添加标签' })).toBeEnabled()
  values = ['更新后的值']
  await dialog.getByRole('button', { name: '添加标签' }).click()
  await expect(page.getByText('标签值已变化，请选择标签管理中的有效值')).toBeVisible()
  expect(submitted).toBe(0)
  values = []
  await dialog.getByRole('button', { name: '取消' }).click()
  await page.locator('.batch-bar').getByRole('button', { name: '添加标签' }).click()
  await expect(dialog.getByText('暂无可用标签值，请先在标签管理中配置。')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '添加标签' })).toBeDisabled()
})

test('无关联素材只需一次删除确认且不显示无关素材明细', async ({ page }) => {
  let deleteCalls = 0
  await mockApi(page, [{ id: 'free-image', name: '未关联.jpg', type: 'image', size: 1024,
    status: 'ready', tags: {}, media: {}, created_at: '2026-10-02T01:00:00Z' }])
  await page.route('**/api/v1/assets/usage-impact', route => json(route, {
    total: 1, affected_count: 0, details_truncated: false, items: [],
  }))
  await page.route('**/api/v1/assets/batch-delete', async route => {
    deleteCalls++
    expect(route.request().postDataJSON().confirm_linked).toBe(false)
    await json(route, { succeeded: ['free-image'], succeeded_count: 1, failed: [], failed_count: 0,
      details: [], details_truncated: false })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /素材库/ }).click()
  await page.getByRole('button', { name: '✓ 全选' }).click()
  await page.locator('.batch-bar').getByRole('button', { name: '删除', exact: true }).click()
  await expect(page.getByLabel('素材使用影响')).toContainText('存在 0 项关联关系')
  await expect(page.locator('.usage-impact-list article')).toHaveCount(0)
  await page.locator('.confirm-dialog').getByRole('button', { name: '确认删除' }).click()
  await expect.poll(() => deleteCalls).toBe(1)
  await expect(page.locator('.confirm-dialog')).toHaveCount(0)
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
  await page.getByRole('button', { name: /素材库/ }).click()

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
  await expect(page.getByRole('button', { name: '导出 CSV' })).toBeVisible()
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
  await expect(detail.getByText('成功（200）')).toBeVisible()
  await expect(detail.getByText('127.0.0.1')).toBeVisible()
  await page.locator('.audit-detail-stage').click({ position: { x: 20, y: 20 } })
  await expect(detail).toHaveCount(0)
  await page.getByPlaceholder('搜索用户、对象、操作或请求 ID').fill('admin')
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await expect(page.getByText('当前页')).toContainText('当前页 1 项')
})

test('系统日志页面翻页、筛选与导出使用相同条件', async ({ page }) => {
  const requestedPages: number[] = []
  const requestedQueries: string[] = []
  let exportedQuery = ''
  let exportedUrl = ''
  await mockApi(page)
  await page.route(/\/api\/v1\/audit-logs(?:\/export)?(?:\?.*)?$/, async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/export')) {
      exportedUrl = url.href
      exportedQuery = url.searchParams.get('q') || ''
      return route.fulfill({ status: 200, contentType: 'text/csv', body: '时间,操作\n' })
    }
    const number = Number(url.searchParams.get('page') || 1)
    requestedPages.push(number)
    requestedQueries.push(url.searchParams.get('q') || '')
    return json(route, { items: [{ id: `log-${number}`, action: 'user.updated', object_type: 'user', object_name: `用户${number}`, actor_username: 'admin', request_id: `request-${number}`, created_at: '2026-10-08T01:00:00Z' }], total: 51 })
  })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /系统日志/ }).click()
  await page.locator('.audit-log-shell').getByRole('button', { name: '›' }).click()
  await expect(page.locator('.audit-log-table')).toContainText('用户2')
  expect(requestedPages).toContain(2)
  await page.getByPlaceholder('搜索用户、对象、操作或请求 ID').fill('admin')
  await page.locator('.audit-log-filters').getByRole('button', { name: '筛选' }).click()
  await expect(page.locator('.audit-log-shell .pagination')).toContainText('第 1 / 2 页')
  expect(requestedQueries).toContain('admin')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出 CSV' }).click()
  await download
  expect(exportedQuery, exportedUrl).toBe('admin')
})

test('自定义用户的菜单权限和操作权限支持全选与取消选择', async ({ page }) => {
  await mockApi(page)
  await page.setViewportSize({ width: 1100, height: 600 })
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')

  await page.getByRole('button', { name: /用户管理/ }).click()
  await page.getByRole('button', { name: '＋ 新增用户', exact: true }).click()
  const userDialog = page.getByRole('heading', { name: '新增用户', exact: true }).locator('..')
  await userDialog.getByLabel('角色').selectOption('custom')

  const permissions = userDialog.getByRole('group', { name: '菜单与操作权限' })
  const bulk = permissions.locator('.permission-bulk-toolbar')
  await permissions.locator('.permission-menu-title').filter({ hasText: '素材库' }).click()
  await expect(permissions.locator('.permission-menu-group').filter({ hasText: '素材库' }).locator('.permission-menu-actions').getByLabel('有权限')).toHaveCount(4)
  await expect(permissions.getByText('上传素材', { exact: true })).toBeVisible()
  await expect.poll(() => permissions.locator('.permission-groups-list').evaluate(element => getComputedStyle(element).overflowY)).toBe('auto')
  await expect.poll(() => userDialog.evaluate(element => getComputedStyle(element).overflowY)).toBe('hidden')
  await permissions.locator('.permission-menu-title').filter({ hasText: '素材库' }).click()
  await bulk.getByRole('button', { name: '全选', exact: true }).click()
  await expect(permissions.locator('.permission-menu-title').getByLabel('有权限')).toHaveCount(13)
  await expect(permissions.locator('.permission-menu-actions').getByLabel('有权限')).toHaveCount(19)
  await bulk.getByRole('button', { name: '取消全选', exact: true }).click()
  await expect(permissions.locator('.permission-menu-title').getByLabel('有权限')).toHaveCount(0)
  await expect(permissions.locator('.permission-menu-actions').getByLabel('有权限')).toHaveCount(0)
})

test('全局搜索可以打开素材结果', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')

  await page.getByRole('combobox', { name: '全局搜索' }).fill('示例')
  await expect(page.locator('.global-search-results')).toContainText('示例素材.jpg')
  await expect(page.locator('.global-search-results')).toContainText('共 12 项')
  await page.getByRole('combobox', { name: '全局搜索' }).press('Enter')
  await expect(page.getByRole('heading', { name: '素材库' })).toBeVisible()
})

test('角色权限变更展示完整影响预览', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /角色管理/ }).click()
  const roleRow = page.locator('.role-management-table .table-row').filter({ hasText: '质检角色' })
  await roleRow.getByRole('button', { name: '编辑' }).click()
  const editor = page.getByRole('heading', { name: '编辑角色' }).locator('..')
  await editor.locator('.permission-menu-title').filter({ hasText: '数据集管理' }).click()
  await editor.getByRole('button', { name: '保存角色' }).click()

  const preview = page.getByRole('heading', { name: '确认更新角色权限' }).locator('../..')
  await expect(preview).toContainText('2受影响用户')
  await expect(preview).toContainText('菜单 · 数据集管理')
  await expect(preview).toContainText('操作 · 创建编辑数据集')
  await expect(preview).toContainText('操作 · 编辑素材')
  await expect(preview).toContainText('zhangsan')
  await expect(preview).toContainText('lisi')
})

test('素材库筛选和表格列设置会按用户持久保存', async ({ page }) => {
  const assetRows = [{ id: 'asset-1', name: '持久化素材.jpg', type: 'image', size: 2048, status: 'ready', tags: {}, media: {}, created_at: '2026-10-09T01:00:00Z' }]
  await mockApi(page, assetRows)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')
  await page.getByRole('button', { name: /素材库/ }).click()

  await page.getByRole('button', { name: '表格', exact: true }).click()
  await page.getByRole('button', { name: '列设置', exact: true }).click()
  const dialog = page.getByRole('heading', { name: '素材库列设置' }).locator('..')
  await dialog.getByRole('button', { name: /备注/ }).click()
  await dialog.getByRole('button', { name: '完成' }).click()
  await page.reload()
  await page.getByRole('button', { name: /素材库/ }).click()

  await expect(page.locator('.asset-custom-table')).toBeVisible()
  await expect(page.locator('.asset-custom-row.head')).toContainText('备注')
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('cv-archive-library:admin') || '{}').libraryView)).toBe('table')
})

test('角色管理锁定管理员并提示绑定用户不可删除', async ({ page }) => {
  await mockApi(page)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), tokens)
  await page.goto('/')

  await page.getByRole('button', { name: /角色管理/ }).click()
  await expect(page.getByRole('heading', { name: '角色管理' })).toBeVisible()
  const adminRole = page.locator('.role-management-table .table-row:not(.head)').filter({ has: page.locator('b', { hasText: /^管理员$/ }) })
  await expect(adminRole.getByRole('button')).toHaveCount(0)
  const customRole = page.locator('.role-management-table .table-row').filter({ hasText: '质检角色' })
  await customRole.getByRole('button', { name: '删除' }).click()
  await page.locator('.confirm-dialog').getByRole('button', { name: '确认删除' }).click()
  await expect(page.getByText('已有用户zhangsan绑定该角色，不可删除')).toBeVisible()
})

test('只有角色菜单但无管理角色权限时隐藏全部角色操作按钮', async ({ page }) => {
  const readOnlyRoleTokens = {
    ...tokens,
    user: { id: 'role-viewer', username: 'role-viewer', roles: ['custom'], menu_permissions: ['roles'], action_permissions: [] },
  } as any
  await mockApi(page, [], 0, readOnlyRoleTokens)
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), readOnlyRoleTokens)
  await page.goto('/')

  await expect(page.getByRole('button', { name: /角色管理/ })).toBeVisible()
  await page.getByRole('button', { name: /角色管理/ }).click()
  await expect(page.getByRole('heading', { name: '角色管理' })).toBeVisible()
  await expect(page.getByRole('button', { name: '＋ 新建角色', exact: true })).toHaveCount(0)
  await expect(page.locator('.role-management-table').getByRole('button', { name: '编辑', exact: true })).toHaveCount(0)
  await expect(page.locator('.role-management-table').getByRole('button', { name: '删除', exact: true })).toHaveCount(0)
})

test('只有用户菜单但无管理用户权限时隐藏全部用户操作按钮', async ({ page }) => {
  const readOnlyUserTokens = {
    ...tokens,
    user: { id: 'user-viewer', username: 'user-viewer', roles: ['custom'], menu_permissions: ['admin'], action_permissions: [] },
  } as any
  await mockApi(page, [], 0, readOnlyUserTokens)
  await page.route('**/api/v1/users', route => json(route, { items: [{ id: 'user-1', username: '普通用户', roles: ['viewer'], status: 'active' }] }))
  await page.addInitScript(value => localStorage.setItem('cv-archive-session', JSON.stringify(value)), readOnlyUserTokens)
  await page.goto('/')

  await page.getByRole('button', { name: /用户管理/ }).click()
  await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()
  await expect(page.getByRole('button', { name: '＋ 新增用户', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '按角色新增', exact: true })).toHaveCount(0)
  await expect(page.locator('.admin-users').getByRole('button', { name: '编辑', exact: true })).toHaveCount(0)
  await expect(page.locator('.admin-users').getByRole('button', { name: '删除', exact: true })).toHaveCount(0)
})
