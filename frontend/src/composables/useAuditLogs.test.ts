import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({ api: { auditLogs: vi.fn(), exportAuditLogs: vi.fn() } }))

import { api } from '../api'
import { useAuditLogs } from './useAuditLogs'

beforeEach(() => vi.clearAllMocks())

describe('系统日志模块', () => {
  it('加载、筛选、分页和重置由模块管理', async () => {
    vi.mocked(api.auditLogs).mockResolvedValue({ items: [{ id: 'log-1' }], total: 51 })
    const logs = useAuditLogs(vi.fn(), vi.fn())
    await logs.load()
    expect(logs.rows.value).toHaveLength(1)
    expect(logs.pages.value).toBe(2)
    logs.query.value = ' admin '
    logs.action.value = 'user.updated'
    logs.applyFilters()
    await vi.waitFor(() => expect(api.auditLogs).toHaveBeenCalledTimes(2))
    expect(vi.mocked(api.auditLogs).mock.calls[1][0]).toMatchObject({ q: 'admin', action: 'user.updated', page: 1 })
    logs.resetFilters()
    expect(logs.query.value).toBe('')
  })

  it('日期无效时拒绝请求和导出', async () => {
    const error = vi.fn()
    const logs = useAuditLogs(vi.fn(), error)
    logs.createdFrom.value = '2026-10-17T12:00'
    logs.createdTo.value = '2026-10-16T12:00'
    await logs.load()
    await logs.exportCsv()
    expect(api.auditLogs).not.toHaveBeenCalled()
    expect(api.exportAuditLogs).not.toHaveBeenCalled()
    expect(error).toHaveBeenCalledWith('开始时间不能晚于结束时间')
  })

  it('导出沿用筛选条件，并提示结果', async () => {
    vi.mocked(api.exportAuditLogs).mockResolvedValue(undefined as any)
    const notify = vi.fn()
    const logs = useAuditLogs(notify, vi.fn())
    logs.objectType.value = 'user'
    await logs.exportCsv()
    expect(api.exportAuditLogs).toHaveBeenCalledWith(expect.objectContaining({ object_type: 'user' }))
    expect(notify).toHaveBeenCalledWith('系统日志已导出')
  })

  it('忽略登出后的过期响应并清除详情', async () => {
    let resolve!: (value: any) => void
    vi.mocked(api.auditLogs).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const logs = useAuditLogs(vi.fn(), vi.fn())
    const pending = logs.load()
    logs.openDetail({ id: 'log-1', action: 'user.updated', object_type: 'user', created_at: '2026-10-16' })
    logs.clear()
    resolve({ items: [{ id: 'stale' }], total: 1 })
    await pending
    expect(logs.rows.value).toEqual([])
    expect(logs.detail.value).toBeNull()
    expect(logs.loading.value).toBe(false)
  })
})
