<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import type { MenuKey } from '../menuPermissions'

type OverviewData = {
  counts?: Record<string, number>
  asset_types?: Record<string, number>
  asset_storage_by_type?: Record<string, { count?: number; size?: number }>
  recent_activity?: Array<{ id: string; action: string; object_name?: string; object_type: string; created_at: string }>
}

const props = defineProps<{
  userId: string | null
  canViewMenu: (menu: MenuKey) => boolean
  assetTypeLabels: Record<string, string>
  auditObjectLabels: Record<string, string>
  auditActionText: (action: string) => string
  formatStorageSize: (bytes: number) => string
}>()
const emit = defineEmits<{ navigate: [page: MenuKey]; error: [message: string] }>()
const data = ref<OverviewData>({ counts: {}, asset_types: {}, asset_storage_by_type: {}, recent_activity: [] })
const loading = ref(false)
const colors: Record<string, string> = { image: '#3b82f6', video: '#8b5cf6', annotation: '#10b981', model: '#f59e0b', archive: '#ef6c57', image_annotation: '#14b8a6', other: '#94a3b8' }
const assetComposition = computed(() => Object.entries(data.value.asset_types || {})
  .map(([type, count]) => ({ type, count: Number(count) || 0 }))
  .sort((left, right) => right.count - left.count))
const maxAssetCount = computed(() => Math.max(0, ...assetComposition.value.map(item => item.count)))
const assetShares = computed(() => {
  const entries = Object.entries(data.value.asset_storage_by_type || {}).map(([type, value]) => ({ type, count: Number(value.count || 0), size: Number(value.size || 0), color: colors[type] || '#64748b' }))
  const sizeTotal = entries.reduce((sum, item) => sum + item.size, 0)
  const total = sizeTotal > 0 ? sizeTotal : entries.reduce((sum, item) => sum + item.count, 0)
  entries.sort((left, right) => (sizeTotal > 0 ? right.size - left.size : right.count - left.count) || left.type.localeCompare(right.type))
  let current = 0
  return entries.map(item => {
    const amount = sizeTotal > 0 ? item.size : item.count
    const start = total ? current / total * 100 : 0
    current += amount
    const end = total ? current / total * 100 : 0
    return { ...item, percentage: total ? amount / total * 100 : 0, start, end }
  })
})
const assetPieStyle = computed(() => ({ background: assetShares.value.length ? `conic-gradient(${assetShares.value.map(item => `${item.color} ${item.start}% ${item.end}%`).join(',')})` : 'var(--soft)' }))

async function refresh() {
  if (!api.session()) return
  loading.value = true
  try { data.value = await api.overview() }
  catch (error) { emit('error', error instanceof Error ? error.message : '系统概览加载失败') }
  finally { loading.value = false }
}

defineExpose({ refresh })
watch(() => props.userId, userId => { if (userId) void refresh() }, { immediate: true })
</script>

<template>
  <section class="page-head"><div><h1>系统概览</h1><p>快速查看资产规模、任务状态和近期操作。</p></div><button class="secondary" @click="refresh">刷新</button></section>
  <section v-if="loading" class="state-panel"><div class="spinner"></div><b>正在加载系统概览</b></section>
  <div v-else class="overview-shell">
    <section class="overview-cards"><article><small>素材总数</small><b>{{data.counts?.assets??'—'}}</b><button v-if="canViewMenu('library')" @click="emit('navigate','library')">查看素材</button></article><article><small>数据集</small><b>{{data.counts?.datasets??'—'}}</b><button v-if="canViewMenu('datasets')" @click="emit('navigate','datasets')">查看数据集</button></article><article><small>生效关系</small><b>{{data.counts?.relations??'—'}}</b><button v-if="canViewMenu('relations')" @click="emit('navigate','relations')">查看关系</button></article><article :class="{warning:data.counts?.failed_jobs}"><small>处理中 / 近 7 日失败</small><b>{{data.counts?.running_jobs??0}} / {{data.counts?.failed_jobs??0}}</b><button v-if="canViewMenu('downloads')" @click="emit('navigate','downloads')">查看任务</button></article></section>
    <section class="overview-panels"><article><h2>素材构成</h2><div v-if="assetComposition.length" class="overview-types"><div v-for="item in assetComposition" :key="item.type"><span>{{assetTypeLabels[item.type]||item.type}}</span><b>{{item.count}}</b><i :style="{width:`${Math.max(6,item.count / (maxAssetCount || 1) * 100)}%`}"></i></div></div><div v-else class="empty compact"><b>暂无素材统计</b></div></article><article><h2>素材占比</h2><div v-if="assetShares.length" class="overview-pie-layout"><div class="overview-pie" :style="assetPieStyle" role="img" aria-label="按素材类型占用空间展示素材占比"><span><b>{{formatStorageSize(assetShares.reduce((sum,item)=>sum+item.size,0))}}</b><small>总占用空间</small></span></div><div class="overview-pie-legend"><div v-for="item in assetShares" :key="item.type"><i :style="{background:item.color}"></i><span>{{assetTypeLabels[item.type]||item.type}}</span><b>{{item.percentage.toFixed(1)}}%</b><small>{{item.count}} 项 · {{formatStorageSize(item.size)}}</small></div></div></div><div v-else class="empty compact"><b>暂无素材占比</b></div></article><article><h2>近期操作</h2><div v-if="data.recent_activity?.length" class="overview-activity"><div v-for="item in data.recent_activity" :key="item.id"><span>{{auditActionText(item.action)}}</span><b>{{item.object_name||auditObjectLabels[item.object_type]||'系统对象'}}</b><small>{{new Date(item.created_at).toLocaleString('zh-CN')}}</small></div></div><div v-else class="empty compact"><b>暂无可展示的操作</b></div></article></section>
  </div>
</template>
