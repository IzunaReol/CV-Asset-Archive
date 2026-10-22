<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { useDialogAccessibility } from '../dialogAccessibility'

type Metric = { id:string; name:string; category:string; description:string; built_in:boolean }
type Category = { id:string; name:string; built_in:boolean }
type Draft = { name:string; category:string; description:string }

const props = defineProps<{ canManage:boolean }>()
const emit = defineEmits<{ notify:[message:string, kind?:'success'|'error'] }>()
const categories = ref<Category[]>([])
const rows = ref<Metric[]>([])
const loading = ref(true)
const saving = ref(false)
const editing = ref<Metric|null>(null)
const dialogOpen = ref(false)
const categoryEditorOpen = ref(false)
const categoryName = ref('')
const categoryEditingId = ref<string|null>(null)
const categoryFormOpen = ref(false)
const pendingCategoryDelete = ref<Category|null>(null)
const pendingDelete = ref<Metric|null>(null)
const collapsedCategories = ref<Set<string>>(new Set())
const draft = ref<Draft>({name:'', category:'图像分类', description:''})
const grouped = computed(() => categories.value.map(category => ({
  category, items: rows.value.filter(row => row.category === category.name),
})))
const dialogCount = computed(() => Number(dialogOpen.value) + Number(categoryEditorOpen.value) + Number(Boolean(pendingDelete.value)) + Number(Boolean(pendingCategoryDelete.value)))
function toggleCategory(id:string) {
  const next = new Set(collapsedCategories.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedCategories.value = next
}

async function load() {
  loading.value = true
  try {
    const [metrics, categoryResult] = await Promise.all([api.metrics(), api.metricCategories()])
    rows.value = metrics.items
    categories.value = categoryResult.items
  }
  catch (error) { emit('notify', error instanceof Error ? error.message : '指标参数加载失败', 'error') }
  finally { loading.value = false }
}
function openCreate() {
  if (!props.canManage) return
  editing.value = null
  draft.value = {name:'', category:categories.value[0]?.name || '', description:''}
  dialogOpen.value = true
}
function openEdit(row:Metric) {
  if (!props.canManage) return
  editing.value = row
  draft.value = {name:row.name, category:row.category, description:row.description}
  dialogOpen.value = true
}
async function save() {
  if (!props.canManage || saving.value || !draft.value.name.trim() || !draft.value.category || !draft.value.description.trim()) return
  saving.value = true
  try {
    const body = {name:draft.value.name.trim(), category:draft.value.category, description:draft.value.description.trim()}
    if (editing.value) await api.updateMetric(editing.value.id, body)
    else await api.createMetric(body)
    dialogOpen.value = false
    emit('notify', editing.value ? '指标参数已更新' : '指标参数已新增')
    await load()
  } catch (error) { emit('notify', error instanceof Error ? error.message : '指标参数保存失败', 'error') }
  finally { saving.value = false }
}
async function saveCategory() {
  if (!props.canManage || saving.value || !categoryName.value.trim()) return
  saving.value = true
  try {
    const result = categoryEditingId.value
      ? await api.updateMetricCategory(categoryEditingId.value, categoryName.value.trim())
      : await api.createMetricCategory(categoryName.value.trim())
    if (categoryEditingId.value && draft.value.category === categories.value.find(item => item.id === categoryEditingId.value)?.name) draft.value.category = result.name
    await load()
    draft.value.category = result.name
    emit('notify', categoryEditingId.value ? '指标分类已更新' : '指标分类已新增')
    categoryFormOpen.value = false
    categoryEditingId.value = null
    categoryName.value = ''
  } catch (error) { emit('notify', error instanceof Error ? error.message : '指标分类保存失败', 'error') }
  finally { saving.value = false }
}
function openCategoryEditor() {
  if (!props.canManage) return
  categoryFormOpen.value = false
  categoryEditingId.value = null
  categoryName.value = ''
  categoryEditorOpen.value = true
}
function openCreateCategory() {
  categoryEditingId.value = null
  categoryName.value = ''
  categoryFormOpen.value = true
}
function openEditCategory(category:Category) {
  categoryEditingId.value = category.id
  categoryName.value = category.name
  categoryFormOpen.value = true
}
async function remove() {
  if (!props.canManage || !pendingDelete.value || saving.value) return
  saving.value = true
  try {
    await api.deleteMetric(pendingDelete.value.id)
    pendingDelete.value = null
    emit('notify', '指标参数已删除')
    await load()
  } catch (error) { emit('notify', error instanceof Error ? error.message : '指标参数删除失败', 'error') }
  finally { saving.value = false }
}
async function removeCategory() {
  if (!props.canManage || !pendingCategoryDelete.value || saving.value) return
  saving.value = true
  try {
    await api.deleteMetricCategory(pendingCategoryDelete.value.id)
    pendingCategoryDelete.value = null
    await load()
    emit('notify', '指标分类已删除')
  } catch (error) { emit('notify', error instanceof Error ? error.message : '指标分类删除失败', 'error') }
  finally { saving.value = false }
}
function closeTopDialog() {
  if (saving.value) return
  if (pendingCategoryDelete.value) pendingCategoryDelete.value = null
  else if (pendingDelete.value) pendingDelete.value = null
  else if (categoryEditorOpen.value) categoryEditorOpen.value = false
  else dialogOpen.value = false
}
useDialogAccessibility(dialogCount, closeTopDialog)
onMounted(load)
</script>

<template>
  <section class="page-head"><div><h1>参数管理</h1><p>配置模型评估指标的名称、分类与描述</p></div><div v-if="canManage" class="primary-actions"><button class="secondary" @click="openCategoryEditor">分类编辑</button><button class="primary" @click="openCreate">＋ 新增指标</button></div></section>
  <div v-if="loading" class="empty">正在加载指标参数…</div>
  <div v-else class="metric-groups">
    <section v-for="group in grouped" :key="group.category.id" class="metric-group">
      <header><button class="metric-category-toggle" type="button" :aria-expanded="!collapsedCategories.has(group.category.id)" :aria-controls="`metric-category-content-${group.category.id}`" @click="toggleCategory(group.category.id)"><span class="metric-category-chevron" aria-hidden="true">⌄</span><h2>{{group.category.name}}</h2></button><div class="metric-category-actions"><span>{{group.items.length}} 项指标</span></div></header>
      <div v-if="!collapsedCategories.has(group.category.id)" :id="`metric-category-content-${group.category.id}`">
      <div v-if="!group.items.length" class="metric-empty">暂无指标</div>
      <div v-else class="metric-table-wrap"><div class="metric-table" :class="{readonly:!canManage}">
        <div class="metric-row metric-head"><span>指标名称</span><span>描述</span><span v-if="canManage">操作</span></div>
        <div v-for="row in group.items" :key="row.id" class="metric-row">
          <b>{{row.name}} <small v-if="row.built_in">预置</small></b>
          <span>{{row.description}}</span>
          <div v-if="canManage" class="metric-actions"><button @click="openEdit(row)">编辑</button><button v-if="!row.built_in" class="danger-inline" @click="pendingDelete=row">删除</button></div>
        </div>
      </div></div></div>
    </section>
  </div>

  <div v-if="dialogOpen" class="modal-stage"><section class="upload-dialog metric-dialog" role="dialog" aria-modal="true" aria-labelledby="metric-dialog-title">
    <button class="close" aria-label="关闭指标弹窗" :disabled="saving" @click="dialogOpen=false">×</button>
    <h2 id="metric-dialog-title">{{editing?'编辑指标':'新增指标'}}</h2>
    <label>指标名称<input v-model="draft.name" maxlength="100" placeholder="例如 准确率 (Accuracy)" :disabled="saving" /></label>
    <label>分类<select v-model="draft.category" :disabled="saving"><option v-for="category in categories" :key="category.id" :value="category.name">{{category.name}}</option></select></label>
    <label>描述<textarea v-model="draft.description" rows="4" maxlength="1000" placeholder="说明指标的含义与统计口径" :disabled="saving" /></label>
    <div class="dialog-actions"><button class="secondary" :disabled="saving" @click="dialogOpen=false">取消</button><button class="primary" :disabled="saving||!draft.name.trim()||!draft.category||!draft.description.trim()" @click="save">{{saving?'保存中…':'保存'}}</button></div>
  </section></div>
  <div v-if="categoryEditorOpen" class="modal-stage"><section class="upload-dialog metric-dialog category-editor-dialog" role="dialog" aria-modal="true" aria-labelledby="metric-category-title">
    <button class="close" aria-label="关闭分类编辑弹窗" :disabled="saving" @click="categoryEditorOpen=false">×</button>
    <h2 id="metric-category-title">分类编辑</h2>
    <div class="category-editor-head"><span>已有分类</span><button class="secondary" :disabled="saving" @click="openCreateCategory">＋ 新增分类</button></div>
    <div class="category-editor-list"><div v-for="category in categories" :key="category.id" class="category-editor-row"><span>{{category.name}}<small v-if="category.built_in">预置</small></span><div v-if="!category.built_in"><button class="secondary" :disabled="saving" @click="openEditCategory(category)">编辑</button><button class="danger-inline" :disabled="saving||rows.some(row=>row.category===category.name)" :title="rows.some(row=>row.category===category.name)?'请先删除或移走该分类下的指标':'删除分类'" @click="pendingCategoryDelete=category">删除</button></div></div></div>
    <div v-if="categoryFormOpen" class="category-editor-form"><label>{{categoryEditingId?'编辑分类':'新增分类'}}<input v-model="categoryName" maxlength="100" placeholder="请输入分类名称" :disabled="saving" @keyup.enter="saveCategory" /></label><div><button class="secondary" :disabled="saving" @click="categoryFormOpen=false">取消</button><button class="primary" :disabled="saving||!categoryName.trim()" @click="saveCategory">{{saving?'保存中…':categoryEditingId?'保存修改':'确认新增'}}</button></div></div>
    <div class="dialog-actions"><button class="secondary" :disabled="saving" @click="categoryEditorOpen=false">关闭</button></div>
  </section></div>
  <div v-if="pendingDelete" class="modal-stage confirm-stage"><section class="upload-dialog compact-dialog confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="metric-delete-title">
    <h2 id="metric-delete-title">删除指标参数</h2><p>确定删除“{{pendingDelete.name}}”吗？</p>
    <div class="dialog-actions"><button class="secondary" :disabled="saving" @click="pendingDelete=null">取消</button><button class="confirm-delete" :disabled="saving" @click="remove">{{saving?'正在处理…':'确认删除'}}</button></div>
  </section></div>
  <div v-if="pendingCategoryDelete" class="modal-stage confirm-stage"><section class="upload-dialog compact-dialog confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="metric-category-delete-title">
    <h2 id="metric-category-delete-title">删除指标分类</h2><p>确定删除“{{pendingCategoryDelete.name}}”分类吗？</p>
    <div class="dialog-actions"><button class="secondary" :disabled="saving" @click="pendingCategoryDelete=null">取消</button><button class="confirm-delete" :disabled="saving" @click="removeCategory">{{saving?'正在处理…':'确认删除'}}</button></div>
  </section></div>
</template>

<style scoped>
.metric-groups{display:grid;gap:20px}.metric-group{border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}.metric-group header{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid var(--line)}.metric-group h2{margin:0;font-size:17px}.metric-group header span{color:var(--muted);font-size:13px}.metric-empty{padding:24px 18px;color:var(--muted)}.metric-table-wrap{overflow-x:auto}.metric-table{min-width:680px}.metric-row{display:grid;grid-template-columns:minmax(180px,1fr) minmax(250px,2fr) 150px;gap:16px;align-items:center;padding:13px 18px;border-top:1px solid var(--line);font-size:13px}.metric-row:first-child{border-top:0}.metric-table.readonly .metric-row{grid-template-columns:minmax(180px,1fr) minmax(250px,2fr)}.metric-head{background:color-mix(in srgb,var(--panel) 94%,var(--ink));color:var(--muted);font-weight:700}.metric-row b{font-weight:650}.metric-row small{margin-left:6px;color:var(--muted);font-weight:400}.metric-actions{display:flex;gap:8px}.metric-actions button{border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--accent);padding:6px 10px}.metric-actions .danger-inline{color:#dc4c4c}.metric-dialog{width:min(520px,calc(100vw - 32px))}.metric-dialog>label{display:grid;gap:7px;margin:14px 0;color:var(--muted);font-size:13px}.metric-dialog input,.metric-dialog select,.metric-dialog textarea{width:100%;box-sizing:border-box;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);padding:10px;font:inherit}.metric-dialog textarea{resize:vertical}.metric-dialog p{color:var(--muted)}
.metric-category-actions{display:flex;align-items:center;gap:12px}.metric-category-actions button{border:1px solid color-mix(in srgb,#dc4c4c 42%,var(--line));border-radius:6px;background:color-mix(in srgb,#dc4c4c 9%,var(--panel));color:#dc4c4c;padding:6px 10px}.metric-category-actions button:disabled{opacity:.45;cursor:not-allowed}
.metric-category-toggle{display:flex;align-items:center;gap:10px;min-width:0;padding:0;border:0;background:transparent;color:var(--ink);cursor:pointer;text-align:left}.metric-category-toggle:hover h2{color:var(--accent)}.metric-category-toggle:focus-visible{outline:2px solid var(--accent);outline-offset:4px;border-radius:3px}.metric-category-chevron{display:inline-block;color:var(--muted);font-size:21px;line-height:1;transition:transform .15s}.metric-category-toggle[aria-expanded="false"] .metric-category-chevron{transform:rotate(-90deg)}
.category-editor-dialog{width:min(620px,calc(100vw - 32px))}.category-editor-head,.category-editor-row{display:flex;align-items:center;justify-content:space-between;gap:12px}.category-editor-head{margin:18px 0 10px;font-weight:700}.category-editor-list{max-height:min(48vh,420px);overflow:auto;border:1px solid var(--line);border-radius:8px}.category-editor-row{padding:11px 14px;border-bottom:1px solid var(--line)}.category-editor-row:last-child{border-bottom:0}.category-editor-row>span{min-width:0;overflow-wrap:anywhere}.category-editor-row small{margin-left:8px;color:var(--muted)}.category-editor-row>div,.category-editor-form>div{display:flex;gap:8px}.category-editor-row button,.category-editor-head button,.category-editor-form button{padding:7px 12px}.category-editor-row .danger-inline{border:1px solid #b6453c;border-radius:6px;background:transparent;color:#b6453c}.category-editor-row button:disabled{opacity:.45;cursor:not-allowed}.category-editor-form{margin-top:16px;padding:14px;border:1px solid var(--line);border-radius:8px}.category-editor-form label{display:grid;gap:7px}.category-editor-form>div{justify-content:flex-end;margin-top:12px}
@media(max-width:760px){.metric-row{padding:12px}}
</style>
