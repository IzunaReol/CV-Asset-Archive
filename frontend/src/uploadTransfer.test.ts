import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  api: {
    initUploadBatch: vi.fn(), completeUploadBatch: vi.fn(),
    initUpload: vi.fn(), uploadSession: vi.fn(), completeUpload: vi.fn(),
  },
}))

import { api } from './api'
import { transferUploads, uploadFileKey } from './uploadTransfer'

beforeEach(() => vi.clearAllMocks())

describe('素材上传传输模块', () => {
  function largeFile() {
    return { name: 'large.zip', size: 64 * 1024 * 1024 + 2, lastModified: 1, type: 'application/zip', slice: vi.fn(() => new Blob(['part'])) } as unknown as File
  }

  it('批量上传保留覆盖目标并分别报告成功与失败', async () => {
    const files = [new File(['a'], 'a.jpg'), new File(['b'], 'b.jpg')]
    vi.mocked(api.initUploadBatch).mockResolvedValue({ items: [
      { index: 0, session: { upload_required: false, upload_session_id: 's1' } },
      { index: 1, session: { upload_required: false, upload_session_id: 's2' } },
    ] })
    vi.mocked(api.completeUploadBatch).mockResolvedValue({ items: [
      { index: 0 }, { index: 1, error: { message: '校验失败' } },
    ] })
    const completed = vi.fn()
    const result = await transferUploads(files, {
      nameConflict: 'overwrite',
      overwriteTargets: new Map([[uploadFileKey(files[0]), 'old-asset']]),
      resolvedUploadType: () => 'image', tags: () => ({ source: ['test'] }),
      uploadRequest: vi.fn(), onCompleted: completed,
    })

    expect(vi.mocked(api.initUploadBatch).mock.calls[0][0][0]).toMatchObject({
      filename: 'a.jpg', expected_overwrite_asset_id: 'old-asset',
    })
    expect(result.succeeded).toBe(1)
    expect(result.failed[0].message).toBe('校验失败')
    expect(result.details.map(item => item.status)).toEqual(['succeeded', 'failed'])
    expect(completed).toHaveBeenCalledTimes(2)
  })

  it('批量初始化失败时逐个记录失败，不遗漏进度', async () => {
    const files = [new File(['a'], 'a.jpg'), new File(['b'], 'b.jpg')]
    vi.mocked(api.initUploadBatch).mockRejectedValue(new Error('服务暂不可用'))
    const completed = vi.fn()
    const result = await transferUploads(files, {
      nameConflict: 'reject', overwriteTargets: new Map(),
      resolvedUploadType: () => 'image', tags: () => ({}),
      uploadRequest: vi.fn(), onCompleted: completed,
    })
    expect(result.failed.map(item => item.message)).toEqual(['服务暂不可用', '服务暂不可用'])
    expect(completed).toHaveBeenCalledTimes(2)
  })

  it('大文件断点续传跳过已上传分片并完成会话', async () => {
    const file = largeFile()
    const storage = new Map([[`cv-archive-upload:${uploadFileKey(file)}`, 'resume-1']])
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) || null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    })
    vi.mocked(api.uploadSession).mockResolvedValue({ size: file.size, asset_type: 'archive', transfer_mode: 'chunks', chunk_count: 2, chunk_size: file.size / 2, uploaded_parts: [0], upload_urls: { '1': 'https://object/part-1' } })
    vi.mocked(api.completeUpload).mockResolvedValue({} as any)
    const uploadRequest = vi.fn().mockResolvedValue(undefined)
    const result = await transferUploads([file], {
      nameConflict: 'reject', overwriteTargets: new Map(), resolvedUploadType: () => 'archive',
      tags: () => ({}), uploadRequest, onCompleted: vi.fn(),
    })
    expect(api.initUpload).not.toHaveBeenCalled()
    expect(uploadRequest).toHaveBeenCalledOnce()
    expect(uploadRequest.mock.calls[0][0]).toBe('https://object/part-1')
    expect(file.slice).toHaveBeenCalledWith(file.size / 2, file.size)
    expect(result.succeeded).toBe(1)
    expect(storage.size).toBe(0)
    vi.unstubAllGlobals()
  })

  it('失效的大文件会话重新初始化；分片失败时保留会话供重试', async () => {
    const file = largeFile()
    const storage = new Map([[`cv-archive-upload:${uploadFileKey(file)}`, 'expired-1']])
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) || null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    })
    vi.mocked(api.uploadSession).mockResolvedValueOnce({ size: 1, asset_type: 'archive' }).mockResolvedValueOnce({ size: file.size, asset_type: 'archive', transfer_mode: 'chunks', chunk_count: 1, chunk_size: file.size, uploaded_parts: [], upload_urls: { '0': 'https://object/part-0' } })
    vi.mocked(api.initUpload).mockResolvedValue({ upload_session_id: 'new-1' } as any)
    const result = await transferUploads([file], {
      nameConflict: 'rename', overwriteTargets: new Map(), resolvedUploadType: () => 'archive',
      tags: () => ({}), uploadRequest: vi.fn().mockRejectedValue(new Error('网络中断')), onCompleted: vi.fn(),
    })
    expect(api.initUpload).toHaveBeenCalledOnce()
    expect(result.failed[0].message).toBe('网络中断')
    expect(storage.get(`cv-archive-upload:${uploadFileKey(file)}`)).toBe('new-1')
    vi.unstubAllGlobals()
  })
})
