import { describe, expect, it } from 'vitest'

import { canDeleteTag, jobAction } from './uiPolicy'

describe('界面操作规则', () => {
  it('默认标签不可删除，自定义标签允许删除', () => {
    expect(canDeleteTag({ built_in: true })).toBe(false)
    expect(canDeleteTag({ built_in: false })).toBe(true)
    expect(canDeleteTag({})).toBe(true)
  })

  it('只为实际可操作的任务返回按钮', () => {
    expect(jobAction({ state: 'succeeded', type: 'export' })).toBe('download')
    expect(jobAction({ state: 'failed', type: 'process_asset' })).toBe('retry')
    expect(jobAction({ state: 'running', type: 'dataset_export' })).toBe('cancel')
    expect(jobAction({ state: 'succeeded', type: 'process_asset' })).toBeNull()
  })
})
