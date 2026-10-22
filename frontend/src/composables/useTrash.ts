import { computed, ref } from 'vue'
import { api } from '../api'

export type TrashAsset = {
  id: string | number; name: string; type: string; tone: string; mark: string
  createdAt: string; preview_url?: string | null
}

export function useTrash(deps: {
  mapAsset: (value: any) => TrashAsset
  refreshAssets: () => Promise<unknown>
  notify: (message: string, kind?: 'success' | 'error') => void
  notifyError: (message: string) => void
  confirm: (message: string, action: () => Promise<void>) => void
  showBatchResult: (title: string, result: any) => void
}) {
  const assets = ref<TrashAsset[]>([])
  const selected = ref<Array<string | number>>([])
  const page = ref(1)
  const pageSize = ref(50)
  const total = ref(0)
  const pages = computed(() => pageSize.value === 0 ? 1 : Math.max(1, Math.ceil(total.value / pageSize.value)))
  const allSelected = computed(() => Boolean(assets.value.length) && assets.value.every(asset => selected.value.includes(asset.id)))
  let generation = 0

  async function load() {
    const requestId = ++generation
    try {
      let result = await api.trash(page.value, pageSize.value === 0 ? 200 : pageSize.value)
      if (pageSize.value === 0) {
        const items = [...result.items]
        const pageCount = Math.ceil(result.total / 200)
        for (let pageNumber = 2; pageNumber <= pageCount; pageNumber += 1) {
          const next = await api.trash(pageNumber, 200)
          items.push(...next.items)
        }
        result = { ...result, items }
      }
      if (requestId !== generation) return
      assets.value = result.items.map(deps.mapAsset)
      total.value = result.total
      selected.value = selected.value.filter(id => assets.value.some(asset => asset.id === id))
    } catch (error) {
      if (requestId === generation) deps.notifyError(error instanceof Error ? error.message : '回收站加载失败')
    }
  }
  function toggle(id: string | number) {
    selected.value = selected.value.includes(id) ? selected.value.filter(item => item !== id) : [...selected.value, id]
  }
  function selectPage() { selected.value = assets.value.map(asset => asset.id) }
  function invertPage() { selected.value = assets.value.filter(asset => !selected.value.includes(asset.id)).map(asset => asset.id) }
  function restore() {
    const ids = selected.value.map(String)
    if (!ids.length) return
    deps.confirm(`确定要还原${ids.length}项吗？`, async () => {
      const result = await api.restoreTrash(ids)
      deps.showBatchResult('批量还原结果', result)
      selected.value = result.failed.map((item: any) => item.id)
      deps.notify(`已还原 ${result.succeeded.length} 项素材`)
      await Promise.all([load(), deps.refreshAssets()])
    })
  }
  function empty() {
    if (!total.value) return
    deps.confirm(`确定要清空回收站中的${total.value}项吗？`, async () => {
      const job = await api.emptyTrash()
      selected.value = []
      deps.notify('已提交后台清理')
      void monitorJob(String(job.id))
    })
  }
  async function monitorJob(jobId: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 1000))
      try {
        const job = await api.job(jobId)
        if (job.state === 'succeeded') {
          const failed = job.result?.failed?.length || 0
          deps.notify(failed ? `回收站清理完成，${failed} 项失败` : '回收站已清空', failed ? 'error' : 'success')
          await Promise.all([load(), deps.refreshAssets()])
          return
        }
        if (job.state === 'failed') { deps.notifyError(job.error?.message || '回收站清理失败'); return }
      } catch { return }
    }
  }
  function clear() {
    generation += 1
    assets.value = []; selected.value = []; total.value = 0; page.value = 1
  }
  return { assets, selected, page, pageSize, total, pages, allSelected, load, toggle, selectPage, invertPage, restore, empty, clear }
}
