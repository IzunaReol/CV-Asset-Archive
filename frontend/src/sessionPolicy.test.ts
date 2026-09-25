import { describe, expect, it } from 'vitest'

import { jobPollDelay, persistedSession } from './sessionPolicy'

describe('会话与轮询策略', () => {
  it('只在存在活动任务时保持三秒轮询', () => {
    expect(jobPollDelay({ page: 'downloads', jobs: [{ state: 'running' }], assets: [] })).toBe(3000)
    expect(jobPollDelay({ page: 'downloads', jobs: [{ state: 'succeeded' }], assets: [] })).toBe(15000)
    expect(jobPollDelay({ page: 'library', jobs: [], assets: [{ status: 'processing' }] })).toBe(3000)
    expect(jobPollDelay({ page: 'datasets', jobs: [], assets: [] })).toBe(30000)
  })

  it('持久化会话不保存任何令牌', () => {
    const stored = persistedSession({
      access_token: 'access-secret',
      refresh_token: 'refresh-secret',
      access_expires_at: '2026-09-25T00:00:00Z',
      user: { username: 'admin' },
    })
    expect(stored.access_token).toBe('')
    expect(stored).not.toHaveProperty('refresh_token')
  })
})
