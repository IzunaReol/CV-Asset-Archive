import { api } from './api'

export type UploadConflictMode = 'reject' | 'overwrite' | 'rename'
export type UploadFailure = { file: File; message: string }
export type UploadOperationDetail = {
  id: string
  name: string
  status: 'succeeded' | 'failed'
  message: string
}

export function uploadFileKey(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`
}

const hashes = new Map<string, string>()
export async function uploadFileHash(file: File) {
  const key = uploadFileKey(file)
  if (hashes.has(key)) return hashes.get(key)
  if (!globalThis.crypto?.subtle || file.size > 64 * 1024 * 1024) return undefined
  const digest = await globalThis.crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  const value = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  hashes.set(key, value)
  return value
}

type TransferOptions = {
  nameConflict: UploadConflictMode
  overwriteTargets: Map<string, string>
  resolvedUploadType: (file: File) => string
  tags: () => Record<string, string[]>
  uploadRequest: (url: string, body: Blob | File, failureMessage: string) => Promise<void>
  onCompleted: () => void
}

export async function transferUploads(files: File[], options: TransferOptions) {
  const { nameConflict, overwriteTargets, resolvedUploadType, tags, uploadRequest, onCompleted } = options
  const failed: UploadFailure[] = []
  const details: UploadOperationDetail[] = []
  let succeeded = 0
  let hasDatasetPackage = false

  const markFailure = (file: File, message: string) => {
    failed.push({ file, message })
    details.push({ id: uploadFileKey(file), name: file.name, status: 'failed', message })
    onCompleted()
  }
  const markSuccess = (file: File) => {
    succeeded += 1
    hasDatasetPackage ||= resolvedUploadType(file) === 'image_annotation'
    details.push({
      id: uploadFileKey(file), name: file.name, status: 'succeeded',
      message: nameConflict === 'overwrite' ? '已覆盖原文件' : '上传完成',
    })
    onCompleted()
  }

  const smallFiles = files.filter(file => file.size < 64 * 1024 * 1024)
  for (let offset = 0; offset < smallFiles.length; offset += 25) {
    const chunk = smallFiles.slice(offset, offset + 25)
    let initialized: any[]
    try {
      initialized = (await api.initUploadBatch(await Promise.all(chunk.map(async file => ({
        filename: file.name, size: file.size, mime_type: file.type || 'application/octet-stream',
        asset_type: resolvedUploadType(file), sha256: await uploadFileHash(file),
        name_conflict: nameConflict,
        expected_overwrite_asset_id: overwriteTargets.get(uploadFileKey(file)) || null,
      }))))).items
    } catch (error) {
      chunk.forEach(file => markFailure(file, error instanceof Error ? error.message : '创建上传任务失败'))
      continue
    }
    const ready: Array<{ file: File; sessionId: string }> = []
    const queue = [...initialized]
    const uploadOne = async () => {
      while (queue.length) {
        const item = queue.shift()!
        const file = chunk[item.index]
        if (item.error) { markFailure(file, item.error.message); continue }
        try {
          if (item.session.upload_required) {
            await uploadRequest(item.session.upload_url, file, '文件上传到对象存储失败')
          }
          ready.push({ file, sessionId: item.session.upload_session_id })
        } catch (error) {
          markFailure(file, error instanceof Error ? error.message : '上传失败')
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(12, queue.length) }, () => uploadOne()))
    if (!ready.length) continue
    try {
      const result = await api.completeUploadBatch(ready.map(item => item.sessionId), tags())
      result.items.forEach((item: any) => {
        const file = ready[item.index].file
        if (item.error) markFailure(file, item.error.message)
        else markSuccess(file)
      })
    } catch (error) {
      ready.forEach(({ file }) => markFailure(file, error instanceof Error ? error.message : '完成上传失败'))
    }
  }

  const largeQueue = files.filter(file => file.size >= 64 * 1024 * 1024)
  const uploadLarge = async () => {
    while (largeQueue.length) {
      const file = largeQueue.shift()!
      const storageKey = `cv-archive-upload:${uploadFileKey(file)}`
      try {
        let sessionId = localStorage.getItem(storageKey)
        let status: any = null
        if (sessionId) {
          status = await api.uploadSession(sessionId).catch(() => null)
          if (status && (status.size !== file.size || status.asset_type !== resolvedUploadType(file))) status = null
        }
        if (!status) {
          localStorage.removeItem(storageKey)
          const initial = await api.initUpload({
            filename: file.name, size: file.size, mime_type: file.type || 'application/octet-stream',
            asset_type: resolvedUploadType(file), sha256: await uploadFileHash(file),
            name_conflict: nameConflict,
            expected_overwrite_asset_id: overwriteTargets.get(uploadFileKey(file)) || null,
          })
          sessionId = initial.upload_session_id
          localStorage.setItem(storageKey, sessionId!)
          status = await api.uploadSession(sessionId!)
        }
        if (status.transfer_mode === 'chunks') {
          const pending = Array.from({ length: status.chunk_count }, (_, index) => index)
            .filter(index => !status.uploaded_parts.includes(index))
          const uploadChunk = async () => {
            while (pending.length) {
              const index = pending.shift()!
              const position = index * status.chunk_size
              await uploadRequest(status.upload_urls[String(index)],
                file.slice(position, Math.min(position + status.chunk_size, file.size)),
                `第 ${index + 1} 个分片上传失败`)
            }
          }
          await Promise.all(Array.from({ length: Math.min(3, pending.length) }, () => uploadChunk()))
        } else if (status.upload_required) {
          throw new Error('上传会话模式不正确，请重新选择文件')
        }
        await api.completeUpload({ upload_session_id: sessionId, tags: tags() })
        localStorage.removeItem(storageKey)
        markSuccess(file)
      } catch (error) {
        markFailure(file, error instanceof Error ? error.message : '上传失败')
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(2, largeQueue.length) }, () => uploadLarge()))
  return { succeeded, failed, details, hasDatasetPackage }
}
