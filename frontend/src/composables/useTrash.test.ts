import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', () => ({ api: { trash: vi.fn(), restoreTrash: vi.fn(), emptyTrash: vi.fn(), job: vi.fn() } }))
import { api } from '../api'
import { useTrash } from './useTrash'

beforeEach(() => vi.clearAllMocks())

function setup() {
  const deps = {
    mapAsset: (value: any) => value,
    refreshAssets: vi.fn().mockResolvedValue(undefined),
    notify: vi.fn(), notifyError: vi.fn(), confirm: vi.fn(), showBatchResult: vi.fn(),
  }
  return { trash: useTrash(deps), deps }
}
const item = (id: number) => ({ id, name: `素材 ${id}`, type: '图片', tone: '', mark: '', createdAt: '' })

describe('回收站模块', () => {
  it('加载、分页与选择均保持在业务模块内', async () => {
    vi.mocked(api.trash).mockResolvedValue({ items: [item(1), item(2)], total: 51 })
    const { trash } = setup()
    await trash.load()
    expect(trash.pages.value).toBe(2)
    trash.toggle(1)
    expect(trash.selected.value).toEqual([1])
    trash.invertPage()
    expect(trash.selected.value).toEqual([2])
    trash.selectPage()
    expect(trash.allSelected.value).toBe(true)
    trash.page.value = 2
    await trash.load()
    expect(api.trash).toHaveBeenLastCalledWith(2, 50)
  })

  it('全部模式按批拉取，切换页面后过滤不可见选择', async () => {
    vi.mocked(api.trash).mockImplementation(async page => ({ items: [item(page)], total: 201 }))
    const { trash } = setup()
    trash.pageSize.value = 0
    trash.selected.value = [99]
    await trash.load()
    expect(api.trash).toHaveBeenCalledTimes(2)
    expect(trash.assets.value.map(asset => asset.id)).toEqual([1, 2])
    expect(trash.selected.value).toEqual([])
    expect(trash.pages.value).toBe(1)
  })

  it('还原要求确认，并刷新回收站及素材库', async () => {
    vi.mocked(api.trash).mockResolvedValue({ items: [item(1)], total: 1 })
    vi.mocked(api.restoreTrash).mockResolvedValue({ succeeded: ['1'], failed: [] } as any)
    const { trash, deps } = setup()
    await trash.load()
    trash.toggle(1)
    trash.restore()
    expect(deps.confirm).toHaveBeenCalledWith('确定要还原1项吗？', expect.any(Function))
    await deps.confirm.mock.calls[0][1]()
    expect(api.restoreTrash).toHaveBeenCalledWith(['1'])
    expect(deps.refreshAssets).toHaveBeenCalledOnce()
    expect(deps.showBatchResult).toHaveBeenCalledWith('批量还原结果', expect.anything())
  })

  it('清空要求确认；登出后丢弃过期列表响应', async () => {
    let resolve!: (value: any) => void
    vi.mocked(api.trash).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const { trash, deps } = setup()
    const pending = trash.load()
    trash.clear()
    resolve({ items: [item(1)], total: 1 })
    await pending
    expect(trash.total.value).toBe(0)
    trash.total.value = 2
    trash.empty()
    expect(deps.confirm).toHaveBeenCalledWith('确定要清空回收站中的2项吗？', expect.any(Function))
  })

  it('空选择不还原，空回收站不清空；加载失败给出提示', async () => {
    vi.mocked(api.trash).mockRejectedValue(new Error('网络中断'))
    const { trash, deps } = setup()
    trash.restore()
    trash.empty()
    expect(deps.confirm).not.toHaveBeenCalled()
    await trash.load()
    expect(deps.notifyError).toHaveBeenCalledWith('网络中断')
  })
})
