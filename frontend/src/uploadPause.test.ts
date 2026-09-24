import { describe, expect, it, vi } from 'vitest'

import { UploadPauseController } from './uploadPause'

describe('上传暂停控制', () => {
  it('暂停会中止当前请求，继续后重新发起', async () => {
    const states: boolean[] = []
    const controller = new UploadPauseController(paused => states.push(paused))
    let attempts = 0
    const upload = controller.request(signal => {
      attempts += 1
      if (attempts > 1) return Promise.resolve({ ok: true } as Response)
      return new Promise<Response>((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    }, '上传失败')

    await vi.waitFor(() => expect(attempts).toBe(1))
    controller.pause()
    controller.resume()
    await upload

    expect(attempts).toBe(2)
    expect(states).toEqual([true, false])
  })

  it('服务端失败时返回中文错误', async () => {
    const controller = new UploadPauseController(() => undefined)
    await expect(
      controller.request(async () => ({ ok: false } as Response), '文件上传到对象存储失败'),
    ).rejects.toThrow('文件上传到对象存储失败')
  })
})
