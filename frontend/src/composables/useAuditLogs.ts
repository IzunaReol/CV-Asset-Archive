import { computed, ref } from 'vue'
import { api } from '../api'

export type AuditLogEntry = {
  id: string
  action: string
  object_type: string
  object_name?: string
  actor_id?: string
  actor_username?: string
  created_at: string
  outcome?: string
  response_status?: number
  client_ip?: string
  request_id?: string
  changes?: Record<string, unknown>
}

export function useAuditLogs(notify: (message: string) => void, notifyError: (message: string) => void) {
  const rows = ref<AuditLogEntry[]>([])
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(50)
  const total = ref(0)
  const query = ref('')
  const action = ref('')
  const objectType = ref('')
  const createdFrom = ref('')
  const createdTo = ref('')
  const detail = ref<AuditLogEntry | null>(null)
  const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  let generation = 0

  function filters() {
    return {
      q: query.value.trim(), action: action.value, object_type: objectType.value,
      created_from: createdFrom.value ? new Date(createdFrom.value).toISOString() : '',
      created_to: createdTo.value ? new Date(createdTo.value).toISOString() : '',
    }
  }
  function validRange() {
    if (createdFrom.value && createdTo.value && new Date(createdFrom.value) > new Date(createdTo.value)) {
      notifyError('开始时间不能晚于结束时间')
      return false
    }
    return true
  }
  async function load() {
    if (!validRange()) return
    const requestId = ++generation
    loading.value = true
    try {
      const result = await api.auditLogs({ page: page.value, page_size: pageSize.value, ...filters() })
      if (requestId !== generation) return
      rows.value = result.items || []
      total.value = Number(result.total || 0)
    } catch (error) {
      if (requestId === generation) notifyError(error instanceof Error ? error.message : '系统日志加载失败')
    } finally {
      if (requestId === generation) loading.value = false
    }
  }
  async function exportCsv() {
    if (!validRange()) return
    try { await api.exportAuditLogs(filters()); notify('系统日志已导出') }
    catch (error) { notifyError(error instanceof Error ? error.message : '系统日志导出失败') }
  }
  function applyFilters() { page.value = 1; void load() }
  function resetFilters() {
    query.value = ''; action.value = ''; objectType.value = ''; createdFrom.value = ''; createdTo.value = ''; page.value = 1
    void load()
  }
  function openDetail(item: AuditLogEntry) { detail.value = item }
  function closeDetail() { detail.value = null }
  function clear() {
    generation++
    rows.value = []; total.value = 0; loading.value = false; detail.value = null
  }

  return { rows, loading, page, pageSize, total, query, action, objectType, createdFrom, createdTo,
    detail, pages, load, exportCsv, applyFilters, resetFilters, openDetail, closeDetail, clear }
}
