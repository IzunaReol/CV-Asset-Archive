<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { api } from '../api'

const props = defineProps<{ jobStateText: (state: string) => string }>()
const emit = defineEmits<{
  open: [groupType: string, item: any]
  error: [message: string]
}>()

const query = ref('')
const open = ref(false)
const loading = ref(false)
const groups = ref<any[]>([])
const activeIndex = ref(-1)
const items = computed(() => groups.value.flatMap(group =>
  group.items.map((item: any) => ({ groupType: group.type, item })),
))
let timer: number | null = null
let requestId = 0

function search() {
  if (timer !== null) window.clearTimeout(timer)
  if (!query.value.trim()) {
    groups.value = []; open.value = false; activeIndex.value = -1
    return
  }
  const requestedQuery = query.value.trim()
  timer = window.setTimeout(async () => {
    const currentId = ++requestId
    loading.value = true; open.value = true
    try {
      const result = await api.globalSearch(requestedQuery)
      if (requestedQuery !== query.value.trim()) return
      groups.value = result.groups || []
      activeIndex.value = items.value.length ? 0 : -1
    } catch (error) {
      emit('error', error instanceof Error ? error.message : '全局搜索失败')
    } finally {
      if (currentId === requestId) loading.value = false
    }
  }, 250)
}

function moveSelection(direction: -1 | 1) {
  if (!open.value || !items.value.length) return
  activeIndex.value = (activeIndex.value + direction + items.value.length) % items.value.length
  requestAnimationFrame(() => document.querySelector<HTMLElement>('.global-search-result.active')?.scrollIntoView({ block: 'nearest' }))
}

function openResult(groupType: string, item: any) {
  open.value = false
  emit('open', groupType, item)
}

function openSelected() {
  const selected = items.value[activeIndex.value]
  if (selected) openResult(selected.groupType, selected.item)
}

function itemIndex(groupType: string, itemId: string | number) {
  return items.value.findIndex(entry => entry.groupType === groupType && String(entry.item.id) === String(itemId))
}

onBeforeUnmount(() => { if (timer !== null) window.clearTimeout(timer) })
</script>

<template>
  <div class="global-search-wrap">
    <label class="global-search"><span>⌕</span><input v-model="query" placeholder="搜索素材、模型、数据集、任务等…" role="combobox" aria-label="全局搜索" :aria-expanded="open" aria-controls="global-search-results" :aria-activedescendant="activeIndex>=0?`global-result-${activeIndex}`:undefined" @input="search" @focus="query&&search()" @keydown.down.prevent="moveSelection(1)" @keydown.up.prevent="moveSelection(-1)" @keydown.enter.prevent="openSelected" @keydown.esc="open=false" /></label>
    <section v-if="open" id="global-search-results" class="global-search-results" role="listbox">
      <div v-if="loading" class="global-search-state">正在搜索…</div>
      <template v-else-if="groups.length"><div v-for="group in groups" :key="group.type" class="global-search-group"><header><b>{{group.label}}</b><small>共 {{group.total??group.items.length}} 项</small></header><button v-for="item in group.items" :id="`global-result-${itemIndex(group.type,item.id)}`" :key="item.id" type="button" role="option" class="global-search-result" :class="{active:itemIndex(group.type,item.id)===activeIndex}" :aria-selected="itemIndex(group.type,item.id)===activeIndex" @mouseenter="activeIndex=itemIndex(group.type,item.id)" @click="openResult(group.type,item)"><span>{{item.name||item.type}}</span><small>{{item.remark||item.description||item.status||props.jobStateText(item.state)}}</small></button></div><div class="global-search-help">↑↓ 选择 · Enter 打开 · Esc 关闭</div></template>
      <div v-else class="global-search-state">没有匹配结果</div>
    </section>
  </div>
</template>
