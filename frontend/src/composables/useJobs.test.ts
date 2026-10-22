import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({ api: { jobs: vi.fn(), retryJob: vi.fn(), cancelJob: vi.fn(), exportDownload: vi.fn() } }))

import { api } from '../api'
import { jobErrorText, jobStateText, useJobs } from './useJobs'

beforeEach(() => vi.clearAllMocks())

describe('任务中心模块', () => {
  it('加载任务、保留未筛选总数并验证日期范围', async () => {
    vi.mocked(api.jobs).mockResolvedValue({ items: [{ id: 'j1' }], total: 3 })
    const error = vi.fn()
    const jobs = useJobs(vi.fn(), error, vi.fn())
    await jobs.load()
    expect(jobs.rows.value).toHaveLength(1)
    expect(jobs.allTotal.value).toBe(3)
    jobs.createdFrom.value = '2026-10-17T00:00'
    jobs.createdTo.value = '2026-10-16T00:00'
    jobs.applyFilters()
    expect(error).toHaveBeenCalledWith('开始时间不能晚于结束时间')
    expect(api.jobs).toHaveBeenCalledTimes(1)
  })

  it('忽略翻页后过期的响应，并可清空登出状态', async () => {
    let resolve!: (value: any) => void
    vi.mocked(api.jobs).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const jobs = useJobs(vi.fn(), vi.fn(), vi.fn())
    const pending = jobs.load()
    jobs.page.value = 2
    resolve({ items: [{ id: 'stale' }], total: 1 })
    await pending
    expect(jobs.rows.value).toEqual([])
    jobs.allTotal.value = 9
    jobs.clear()
    expect(jobs.allTotal.value).toBe(0)
  })

  it('统一转换任务状态和错误文案', () => {
    expect(jobStateText('succeeded')).toBe('已完成')
    expect(jobErrorText('asset not found')).toBe('素材不存在')
  })

  it('有效筛选转换日期并支持重置', async () => {
    vi.mocked(api.jobs).mockResolvedValue({ items: [], total: 0 })
    const jobs = useJobs(vi.fn(), vi.fn(), vi.fn())
    jobs.typeFilter.value = 'export'
    jobs.createdFrom.value = '2026-10-16T08:00'
    jobs.createdTo.value = '2026-10-17T08:00'
    jobs.applyFilters()
    await vi.waitFor(() => expect(api.jobs).toHaveBeenCalledOnce())
    expect(vi.mocked(api.jobs).mock.calls[0][2]).toBe('export')
    expect(vi.mocked(api.jobs).mock.calls[0][4]).toContain('2026-10')
    jobs.resetFilters()
    await vi.waitFor(() => expect(api.jobs).toHaveBeenCalledTimes(2))
    expect(jobs.typeFilter.value).toBe('')
  })

  it('页码超出结果后回到末页', async () => {
    vi.mocked(api.jobs).mockResolvedValueOnce({ items: [], total: 1 }).mockResolvedValueOnce({ items: [{ id: 'last' }], total: 1 })
    const jobs = useJobs(vi.fn(), vi.fn(), vi.fn())
    jobs.page.value = 3
    await jobs.load()
    expect(jobs.page.value).toBe(1)
    expect(jobs.rows.value[0].id).toBe('last')
  })

  it('下载、重试与取消通过独立模块完成', async () => {
    vi.mocked(api.jobs).mockResolvedValue({ items: [], total: 0 })
    vi.mocked(api.exportDownload).mockResolvedValue({ download_url: 'https://example.test/export' })
    vi.mocked(api.retryJob).mockResolvedValue({} as any)
    vi.mocked(api.cancelJob).mockResolvedValue({} as any)
    const open = vi.fn()
    vi.stubGlobal('window', { open })
    let action!: () => Promise<void>
    const confirm = vi.fn((_message, callback) => { action = callback })
    const notify = vi.fn()
    const jobs = useJobs(notify, vi.fn(), confirm)
    await jobs.download('j1')
    expect(open).toHaveBeenCalledWith('https://example.test/export', '_blank', 'noopener')
    await jobs.retry('j1')
    jobs.cancel({ id: 'j1', type: 'export' })
    expect(confirm).toHaveBeenCalledWith('确定取消任务“素材导出”吗？', expect.any(Function))
    await action()
    expect(api.retryJob).toHaveBeenCalledWith('j1')
    expect(api.cancelJob).toHaveBeenCalledWith('j1')
    expect(notify).toHaveBeenCalledTimes(2)
    vi.unstubAllGlobals()
  })
})
