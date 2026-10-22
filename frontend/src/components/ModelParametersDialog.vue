<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

type Metric = { id:string; name:string; category:string; description:string; value:string|null }
const props = defineProps<{ assetId:string; assetName:string; canEdit:boolean }>()
const emit = defineEmits<{ close:[]; saved:[]; notify:[message:string, kind?:'success'|'error'] }>()
const rows = ref<Metric[]>([])
const values = ref<Record<string,string>>({})
const loading = ref(true)
const saving = ref(false)
const grouped = computed(() => {
  const groups = new Map<string,Metric[]>()
  for (const row of rows.value) {
    if (!groups.has(row.category)) groups.set(row.category, [])
    groups.get(row.category)!.push(row)
  }
  return [...groups].map(([name, items]) => ({name, items}))
})

async function load() {
  loading.value = true
  try {
    const result = await api.modelParameters(props.assetId)
    rows.value = result.items
    values.value = Object.fromEntries(result.items.map(item => [item.id, item.value || '']))
  } catch (error) {
    emit('notify', error instanceof Error ? error.message : '模型参数加载失败', 'error')
  } finally { loading.value = false }
}

async function save() {
  if (!props.canEdit || saving.value) return
  saving.value = true
  try {
    const payload = Object.fromEntries(rows.value.map(item => [item.id, values.value[item.id]?.trim() || null]))
    await api.updateModelParameters(props.assetId, payload)
    emit('notify', '模型参数已保存')
    emit('saved')
    emit('close')
  } catch (error) {
    emit('notify', error instanceof Error ? error.message : '模型参数保存失败', 'error')
  } finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <div class="modal-stage model-parameters-stage"><section class="upload-dialog model-parameters-dialog" role="dialog" aria-modal="true" aria-labelledby="model-parameters-title">
    <button class="close" aria-label="关闭参数配置弹窗" :disabled="saving" @click="emit('close')">×</button>
    <h2 id="model-parameters-title">参数配置</h2><p class="model-parameters-name">{{assetName}}</p>
    <div v-if="loading" class="model-parameters-empty">正在加载模型参数…</div>
    <div v-else-if="!rows.length" class="model-parameters-empty">暂无可配置参数，请先在参数管理中新增指标。</div>
    <div v-else class="model-parameters-groups">
      <section v-for="group in grouped" :key="group.name"><h3>{{group.name}}</h3>
        <label v-for="row in group.items" :key="row.id" class="model-parameter-row"><span><b>{{row.name}}</b><small v-if="row.description">{{row.description}}</small></span><input v-model="values[row.id]" :aria-label="row.name" :disabled="!canEdit||saving" maxlength="200" placeholder="未配置" /></label>
      </section>
    </div>
    <div class="dialog-actions"><button class="secondary" :disabled="saving" @click="emit('close')">{{canEdit?'取消':'关闭'}}</button><button v-if="canEdit" class="primary" :disabled="loading||saving||!rows.length" @click="save">{{saving?'保存中…':'保存参数'}}</button></div>
  </section></div>
</template>

<style scoped>
.model-parameters-stage{z-index:100}.model-parameters-dialog{width:min(680px,calc(100vw - 32px));max-height:min(85vh,840px);display:flex;flex-direction:column}.model-parameters-dialog h2{margin-bottom:4px}.model-parameters-name{margin:0 0 16px;color:var(--muted);overflow-wrap:anywhere}.model-parameters-groups{overflow-y:auto;min-height:0;padding-right:4px}.model-parameters-groups section{margin-bottom:18px;border:1px solid var(--line);border-radius:8px;overflow:hidden}.model-parameters-groups h3{margin:0;padding:12px 14px;background:var(--accent-soft);font-size:15px}.model-parameter-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(150px,210px);align-items:center;gap:16px;padding:11px 14px;border-top:1px solid var(--line)}.model-parameter-row>span{display:grid;gap:4px;min-width:0}.model-parameter-row b{font-size:13px}.model-parameter-row small{color:var(--muted);font-size:12px}.model-parameter-row input{box-sizing:border-box;width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);font:inherit}.model-parameter-row input::placeholder{color:var(--muted)}.model-parameters-empty{padding:28px 8px;color:var(--muted);text-align:center}@media(max-width:600px){.model-parameter-row{grid-template-columns:1fr;gap:8px}}
</style>
