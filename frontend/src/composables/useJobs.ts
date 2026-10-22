import { computed, ref } from 'vue'
import { api } from '../api'

export const jobTypeLabels: Record<string, string> = { export: '素材导出', dataset_export: '数据集导出', trash_empty: '清空回收站' }
export const jobStateLabels: Record<string, string> = { queued: '等待处理', running: '处理中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }

export function jobTypeText(type: string) { return jobTypeLabels[type] || type }
export function jobStateText(state: string) { return jobStateLabels[state] || state }
export function jobNameText(job: any) { return job.name || `${jobTypeText(job.type)}任务` }
export function jobSizeText(job: any) {
  const size = Number(job.result?.size || 0)
  return size > 0 ? `${(size / 1024 / 1024).toFixed(2)} MB` : '—'
}
export function jobErrorText(message: string) {
  if (message === 'ZIP does not contain YOLO label files') return '压缩包中没有 YOLO 标注文件'
  const invalid = message.match(/^YOLO package contains (\d+) invalid label rows$/)
  if (invalid) return `YOLO 压缩包包含 ${invalid[1]} 行无效标注`
  return ({ 'asset not found': '素材不存在', 'job not found': '任务不存在', 'export selection expired': '导出选择范围已过期', 'no exportable assets': '没有可导出的素材' } as Record<string, string>)[message] || message
}

export function useJobs(
  notify: (message: string) => void,
  notifyError: (message: string) => void,
  askConfirmation: (message: string, action: () => Promise<void>) => void,
) {
  const rows = ref<any[]>([])
  const total = ref(0)
  const allTotal = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const typeFilter = ref('')
  const stateFilter = ref('')
  const createdFrom = ref('')
  const createdTo = ref('')
  const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

  async function load() {
    const requestedPage = page.value
    const requestedPageSize = pageSize.value
    const requestedType = typeFilter.value
    const requestedState = stateFilter.value
    const requestedFrom = createdFrom.value
    const requestedTo = createdTo.value
    try {
      const result = await api.jobs(requestedPage, requestedPageSize, requestedType, requestedState, requestedFrom ? new Date(requestedFrom).toISOString() : '', requestedTo ? new Date(requestedTo).toISOString() : '')
      if (requestedPage !== page.value || requestedPageSize !== pageSize.value) return
      if (requestedType !== typeFilter.value || requestedState !== stateFilter.value || requestedFrom !== createdFrom.value || requestedTo !== createdTo.value) return
      const lastPage = Math.max(1, Math.ceil(result.total / requestedPageSize))
      if (requestedPage > lastPage) { page.value = lastPage; await load(); return }
      rows.value = result.items
      total.value = result.total
      if (!requestedType && !requestedState && !requestedFrom && !requestedTo) allTotal.value = result.total
    } catch (error) { notifyError(error instanceof Error ? error.message : '任务加载失败') }
  }

  async function download(id: string) {
    try { window.open((await api.exportDownload(id)).download_url, '_blank', 'noopener') }
    catch (error) { notifyError(error instanceof Error ? error.message : '下载失败') }
  }
  async function retry(id: string) {
    try { await api.retryJob(id); notify('任务已重新提交'); await load() }
    catch (error) { notifyError(error instanceof Error ? error.message : '任务重试失败') }
  }
  function cancel(job: any) {
    askConfirmation(`确定取消任务“${job.name || jobTypeText(job.type)}”吗？`, async () => {
      try { await api.cancelJob(job.id); notify('任务已取消'); await load() }
      catch (error) { notifyError(error instanceof Error ? error.message : '任务取消失败') }
    })
  }
  function resetFilters() {
    typeFilter.value = ''; stateFilter.value = ''; createdFrom.value = ''; createdTo.value = ''; page.value = 1
    void load()
  }
  function applyFilters() {
    if (createdFrom.value && createdTo.value && new Date(createdFrom.value) > new Date(createdTo.value)) {
      notifyError('开始时间不能晚于结束时间')
      return
    }
    page.value = 1
    void load()
  }
  function clear() { rows.value = []; total.value = 0; allTotal.value = 0 }

  return { rows, total, allTotal, page, pageSize, typeFilter, stateFilter, createdFrom, createdTo, pages, load, download, retry, cancel, resetFilters, applyFilters, clear }
}
