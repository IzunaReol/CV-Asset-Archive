import { describe, expect, it, vi } from 'vitest'
import { useConfirmation } from './useConfirmation'

describe('确认弹窗流程', () => {
  it('有关联素材需要二次确认后才执行删除', async () => {
    const action = vi.fn()
    const dialog = useConfirmation(vi.fn())
    dialog.askConfirmation('确定删除吗？', action, { affected_count: 2 })
    dialog.deleteConfirmationStage.value = 1
    await dialog.runConfirmedAction()
    expect(action).not.toHaveBeenCalled()
    expect(dialog.deleteConfirmationStage.value).toBe(2)
    await dialog.runConfirmedAction()
    expect(action).toHaveBeenCalledOnce()
    expect(dialog.confirmOpen.value).toBe(false)
  })

  it('普通确认可取消，未确认不执行操作', async () => {
    const action = vi.fn()
    const dialog = useConfirmation(vi.fn())
    await dialog.runConfirmedAction()
    dialog.askConfirmation('确定删除吗？', action)
    dialog.cancelConfirmation()
    await dialog.runConfirmedAction()
    expect(action).not.toHaveBeenCalled()
    expect(dialog.confirmOpen.value).toBe(false)
  })

  it('覆盖操作先关闭弹窗，再执行上传', async () => {
    const dialog = useConfirmation(vi.fn())
    const action = vi.fn(() => { expect(dialog.confirmOpen.value).toBe(false) })
    dialog.askConfirmation('覆盖原文件吗？', action)
    expect(dialog.confirmTitle.value).toBe('覆盖确认')
    await dialog.runConfirmedAction()
    expect(action).toHaveBeenCalledOnce()
  })

  it('操作失败提示错误并保持弹窗，处理期间不可取消', async () => {
    const error = vi.fn()
    const dialog = useConfirmation(error)
    let reject!: (reason: Error) => void
    dialog.askConfirmation('撤销关联吗？', () => new Promise((_resolve, fail) => { reject = fail }))
    const pending = dialog.runConfirmedAction()
    expect(dialog.confirmBusy.value).toBe(true)
    dialog.cancelConfirmation()
    expect(dialog.confirmOpen.value).toBe(true)
    reject(new Error('请求失败'))
    await pending
    expect(error).toHaveBeenCalledWith('请求失败')
    expect(dialog.confirmBusy.value).toBe(false)
    expect(dialog.confirmOpen.value).toBe(true)
  })

  it('还原、撤销和清空操作使用对应标题与按钮', async () => {
    const dialog = useConfirmation(vi.fn())
    dialog.askConfirmation('确认还原吗？', vi.fn())
    expect(dialog.confirmTitle.value).toBe('还原确认')
    expect(dialog.confirmActionText.value).toBe('确认还原')
    dialog.askConfirmation('撤销关联吗？', vi.fn())
    expect(dialog.confirmTitle.value).toBe('撤销确认')
    expect(dialog.confirmActionText.value).toBe('确认撤销')
    dialog.askConfirmation('清空回收站吗？', vi.fn())
    expect(dialog.confirmActionText.value).toBe('确认清空')
    dialog.askConfirmation('删除素材吗？', vi.fn(), { affected_count: 0 })
    dialog.deleteConfirmationStage.value = 1
    await dialog.runConfirmedAction()
    expect(dialog.confirmOpen.value).toBe(false)
  })
})
