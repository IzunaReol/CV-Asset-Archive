<script setup lang="ts">
import { useTrash, type TrashAsset } from '../composables/useTrash'

const props = defineProps<{
  trash: ReturnType<typeof useTrash>
  canManage: boolean
  canDisplayMediaPreview: (asset: TrashAsset) => boolean
}>()
const { assets, selected, page, pageSize, total, pages, allSelected,
  load, toggle, selectPage, invertPage, restore, empty } = props.trash
</script>

<template>
  <section class="page-head">
    <div><h1>回收站</h1></div>
    <div class="primary-actions">
      <button v-if="selected.length" class="secondary" @click="selected=[]">× 取消选择</button>
      <button class="secondary" :disabled="!assets.length || allSelected" @click="selectPage">✓ 全选</button>
      <button class="secondary" :disabled="!assets.length" @click="invertPage">⇄ 反选</button>
      <button v-if="canManage" class="secondary danger" :disabled="!total" @click="empty">清空回收站</button>
      <button v-if="canManage" class="primary" :disabled="!selected.length" @click="restore">还原</button>
    </div>
  </section>
  <section class="trash-shell content-panel">
    <div class="toolbar"><div>当前页 <b>{{assets.length}}</b> 项 <span>· 全部 {{total}} 项</span></div></div>
    <div v-if="selected.length" class="batch-bar"><b>已选 {{selected.length}} 项</b><button v-if="canManage" @click="restore">还原</button></div>
    <div v-if="assets.length" class="asset-grid">
      <article v-for="asset in assets" :key="asset.id" class="asset-card" :class="{selected:selected.includes(asset.id)}">
        <div class="asset-preview" :style="{background:asset.tone}">
          <img v-if="canDisplayMediaPreview(asset)" :src="asset.preview_url!" :alt="asset.name" />
          <span v-if="asset.type==='视频' && canDisplayMediaPreview(asset)" class="play-badge">▶</span>
          <span v-if="!canDisplayMediaPreview(asset)" class="visual-code">{{asset.type==='图片'?'IMG':asset.type==='视频'?'VIDEO':asset.type==='模型'?'MODEL':'DATA'}}</span>
          <small>{{asset.mark}}</small>
        </div>
        <button class="selector" :aria-label="`选择 ${asset.name}`" @click="toggle(asset.id)">{{selected.includes(asset.id)?'✓':''}}</button>
        <div class="asset-info"><b :title="asset.name">{{asset.name}}</b><small>{{asset.type}} · 删除于 {{asset.createdAt}}</small></div>
      </article>
    </div>
    <div v-else class="empty"><b>回收站为空</b><p>从素材库删除的素材会显示在这里。</p></div>
    <div v-if="total" class="pagination">
      <span>第 {{page}} / {{pages}} 页</span>
      <label>每页 <select v-model="pageSize" @change="page=1;load()"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option><option :value="0">全部</option></select> 项</label>
      <button :disabled="page===1" @click="page--;load()">‹</button><button :disabled="page===pages" @click="page++;load()">›</button>
    </div>
  </section>
</template>
