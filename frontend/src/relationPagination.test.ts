import { describe, expect, it } from 'vitest'
import { nearbyPages } from './relationPagination'

describe('nearbyPages', () => {
  it('keeps the first, last and nearby pages', () => {
    expect(nearbyPages(20, 10)).toEqual([1, 9, 10, 11, 20])
  })

  it('does not duplicate pages near the boundaries', () => {
    expect(nearbyPages(3, 1)).toEqual([1, 2, 3])
    expect(nearbyPages(20, 99)).toEqual([1, 19, 20])
  })
})
