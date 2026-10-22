<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import type { MenuKey } from '../menuPermissions'

type Counts = Record<'image'|'video'|'annotation'|'archive'|'other', number>
type Dataset = { id:string; name:string; current_version?:string|null; updated_at?:string; counts:Counts }
type Model = { id:string; name:string; remark:string; updated_at?:string; sources:string[]; versions:string[]; configured_parameters?:Array<{id:string;name:string;category:string;value:string}> }
type FileRow = { id:string; name:string; type:string; size?:number; tags?:{algorithm?:string|string[]}; updated_at?:string }
type Project = { name:string; dataset_count:number; dataset_counts:Counts; datasets:Dataset[]; model_count:number; models:Model[]; file_count:number; file_counts:Counts; files:FileRow[]; files_truncated:boolean }
type Overview = { available_projects:string[]; selected_projects:string[]; summary:{project_count:number;dataset_count:number;model_count:number;file_count:number}; projects:Project[] }

const props = defineProps<{ canViewMenu:(menu:MenuKey)=>boolean; formatStorageSize:(bytes:number)=>string }>()
const emit = defineEmits<{ dataset:[id:string]; asset:[id:string]; error:[message:string] }>()
const data = ref<Overview|null>(null)
const selected = ref<string[]>([])
const pickerOpen = ref(false)
const search = ref('')
const loading = ref(false)
let requestGeneration = 0
const available = computed(() => data.value?.available_projects || [])
const visibleOptions = computed(() => available.value.filter(item => item.toLowerCase().includes(search.value.trim().toLowerCase())))
const summary = computed(() => data.value?.summary || {project_count:0,dataset_count:0,model_count:0,file_count:0})
const populatedProjects = computed(() => (data.value?.projects || []).filter(project => project.dataset_count || project.model_count || project.file_count))
const countLabels: Array<[keyof Counts,string]> = [['image','图片'],['video','视频'],['annotation','标注'],['archive','压缩文件'],['other','其他']]
const fileTypeLabels: Record<string,string> = {image:'图片',video:'视频',annotation:'标注',archive:'压缩文件',image_annotation:'图片+标注',other:'其他'}

function dateText(value?:string) { return value ? new Date(value).toLocaleString('zh-CN') : '—' }
function algorithmText(value?:string|string[]) { return Array.isArray(value) ? value.join('、') || '未设置' : value || '未设置' }
async function load(initial=false) {
  const requestId = ++requestGeneration
  if (!initial && !selected.value.length) {
    if (data.value) data.value = { ...data.value, selected_projects:[], projects:[], summary:{project_count:0,dataset_count:0,model_count:0,file_count:0} }
    return
  }
  loading.value = true
  try {
    const response:Overview = await api.projectOverview(initial ? [] : selected.value)
    if (requestId !== requestGeneration) return
    data.value = response
    selected.value = response.selected_projects
  } catch (error) {
    if (requestId === requestGeneration) emit('error', error instanceof Error ? error.message : '项目概览加载失败')
  } finally {
    if (requestId === requestGeneration) loading.value = false
  }
}
function toggleProject(project:string) {
  selected.value = selected.value.includes(project) ? selected.value.filter(item=>item!==project) : [...selected.value,project]
  void load()
}
function selectAll() { selected.value = [...available.value]; void load() }
function clearAll() { selected.value = []; void load() }
onMounted(() => { void load(true) })
</script>

<template>
  <section class="page-head project-head">
    <div><h1>项目概览</h1><p>按项目查看数据集、模型与文件。</p></div>
    <div class="project-picker">
      <button class="secondary project-picker-trigger" type="button" :aria-expanded="pickerOpen" @click="pickerOpen=!pickerOpen"><span class="project-picker-label" :title="selected.join('、')">所属项目：{{selected.length===1?selected[0]:selected.length===available.length&&available.length?'全部项目':selected.length?`已选 ${selected.length} 个`:'请选择项目'}}</span><span>⌄</span></button>
      <div v-if="pickerOpen" class="project-picker-panel">
        <input v-model="search" aria-label="搜索项目" placeholder="搜索项目" />
        <div class="project-picker-actions"><button type="button" @click="selectAll">全选</button><button type="button" @click="clearAll">清空</button></div>
        <div class="project-picker-options" role="group" aria-label="项目筛选">
          <label v-for="project in visibleOptions" :key="project"><input type="checkbox" :checked="selected.includes(project)" @change="toggleProject(project)" />{{project}}</label>
          <p v-if="!visibleOptions.length">暂无匹配项目</p>
        </div>
      </div>
    </div>
  </section>
  <section v-if="loading && !data" class="state-panel"><b>正在加载项目概览…</b></section>
  <template v-else>
    <section class="project-stat-grid" aria-label="项目统计">
      <article><small>已选项目</small><b>{{summary.project_count}}</b><span>个</span></article>
      <article><small>数据集</small><b>{{summary.dataset_count}}</b><span>个</span></article>
      <article><small>模型</small><b>{{summary.model_count}}</b><span>个</span></article>
      <article><small>其他文件</small><b>{{summary.file_count}}</b><span>项</span></article>
    </section>
    <p v-if="loading" class="project-count-note">正在刷新…</p>
    <section v-if="!available.length" class="empty project-empty"><b>暂无项目</b><p>请先在标签管理的“项目”字段中添加项目值。</p></section>
    <section v-else-if="!selected.length" class="empty project-empty"><b>请选择项目</b><p>通过右上角筛选框选择一个或多个项目。</p></section>
    <section v-else-if="!populatedProjects.length" class="empty project-empty"><b>所选项目暂无内容</b><p>暂无关联的数据集、模型或文件。</p></section>
    <div v-else class="project-sections">
      <section v-for="project in populatedProjects" :key="project.name" class="project-section">
        <header class="project-section-head"><div><small>PROJECT</small><h2>{{project.name}}</h2></div><span>{{project.dataset_count}} 个数据集 · {{project.model_count}} 个模型 · {{project.file_count}} 项文件</span></header>
        <div v-if="project.dataset_count" class="project-module">
          <div class="project-module-head"><h3>数据集情况</h3></div>
          <div v-if="project.datasets.length" class="project-table-scroll"><div class="project-dataset-table">
            <div class="project-dataset-row heading"><span>数据集</span><span>当前版本</span><span>图片</span><span>视频</span><span>标注</span><span>压缩文件</span><span>其他</span><span>更新时间</span></div>
            <button v-for="dataset in project.datasets" :key="dataset.id" class="project-dataset-row" type="button" @click="emit('dataset',dataset.id)"><b>{{dataset.name}}</b><span>{{dataset.current_version||'未发布'}}</span><span>{{dataset.counts.image}}</span><span>{{dataset.counts.video}}</span><span>{{dataset.counts.annotation}}</span><span>{{dataset.counts.archive}}</span><span>{{dataset.counts.other}}</span><small>{{dateText(dataset.updated_at)}}</small></button>
            <div class="project-dataset-row total"><b>合计</b><span>{{project.dataset_count}} 个数据集</span><span>{{project.dataset_counts.image}}</span><span>{{project.dataset_counts.video}}</span><span>{{project.dataset_counts.annotation}}</span><span>{{project.dataset_counts.archive}}</span><span>{{project.dataset_counts.other}}</span><span>—</span></div>
          </div></div>
        </div>
        <div v-if="project.model_count" class="project-module">
          <div class="project-module-head"><h3>模型情况</h3></div>
          <div v-if="project.models.length" class="project-model-grid"><article v-for="model in project.models" :key="model.id" class="project-model-card">
            <div class="project-model-title"><span>MODEL</span><button type="button" @click="emit('asset',model.id)">{{model.name}}</button></div>
            <p v-if="model.remark">模型备注：{{model.remark}}</p>
            <small>来源：{{model.sources.join('／')}}</small>
            <small v-if="model.versions.length">关联版本：{{model.versions.join('、')}}</small>
            <div v-if="model.configured_parameters?.length" class="project-model-parameters"><span v-for="parameter in model.configured_parameters" :key="parameter.id" :title="parameter.category+' · '+parameter.name"><b>{{parameter.name}}</b>：{{parameter.value}}</span></div>
          </article></div>
        </div>
        <div v-if="project.file_count" class="project-module">
          <div class="project-module-head"><h3>其他文件</h3><span class="project-type-summary">{{countLabels.filter(([key])=>project.file_counts[key]).map(([key,label])=>`${label} ${project.file_counts[key]}`).join(' · ')||'暂无文件'}}</span></div>
          <div v-if="project.files.length" class="project-table-scroll"><div class="project-file-table">
            <div class="project-file-row heading"><span>文件名</span><span>类型</span><span>大小</span><span>所属算法</span><span>更新时间</span></div>
            <button v-for="file in project.files" :key="file.id" type="button" class="project-file-row" @click="emit('asset',file.id)"><b :title="file.name">{{file.name}}</b><span>{{fileTypeLabels[file.type]||file.type}}</span><span>{{formatStorageSize(Number(file.size||0))}}</span><span>{{algorithmText(file.tags?.algorithm)}}</span><small>{{dateText(file.updated_at)}}</small></button>
          </div></div>
          <p v-if="project.files_truncated" class="project-preview-note">当前展示最近 50 项，共 {{project.file_count}} 项。</p>
        </div>
      </section>
    </div>
  </template>
</template>

<style scoped>
.project-head{align-items:flex-start}.project-head p{margin:7px 0 0;color:var(--muted)}.project-picker{position:relative;z-index:20}.project-picker-trigger{min-width:220px;display:flex;justify-content:space-between;gap:16px}.project-picker-panel{position:absolute;right:0;top:calc(100% + 8px);width:min(310px,calc(100vw - 32px));padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);box-shadow:0 16px 36px #0002}.project-picker-panel>input{box-sizing:border-box;width:100%;padding:9px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink)}.project-picker-actions{display:flex;justify-content:space-between;margin:9px 0}.project-picker-actions button,.project-module-head button{border:0;background:transparent;color:var(--accent);font-weight:700;cursor:pointer}.project-picker-options{max-height:220px;overflow:auto}.project-picker-options label{display:flex;align-items:center;gap:9px;padding:8px;color:var(--ink);cursor:pointer}.project-picker-options input{accent-color:var(--accent)}.project-picker-options p{padding:10px;color:var(--muted)}.project-stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.project-stat-grid article{display:flex;align-items:baseline;gap:5px;padding:18px;border:1px solid var(--line);border-radius:10px;background:var(--panel)}.project-stat-grid small{display:block;width:100%;color:var(--muted)}.project-stat-grid b{font-size:28px;color:var(--ink)}.project-stat-grid span{color:var(--muted)}.project-count-note{margin:12px 0 20px;color:var(--muted);font-size:12px}.project-empty{margin-top:18px}.project-sections{display:grid;gap:22px}.project-section{overflow:hidden;border:1px solid var(--line);border-radius:12px;background:var(--panel)}.project-section-head{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:20px 22px;background:var(--accent-soft)}.project-section-head small{font-size:10px;letter-spacing:.16em;color:var(--accent)}.project-section-head h2{margin:3px 0 0;font-size:22px;color:var(--ink)}.project-section-head>span{color:var(--muted);font-size:12px}.project-module{padding:20px 22px;border-top:1px solid var(--line)}.project-module-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}.project-module-head h3{margin:0;color:var(--ink);font-size:16px}.project-module-head button:disabled{opacity:.4;cursor:not-allowed}.project-module-empty{margin:0;padding:18px;border:1px dashed var(--line);border-radius:8px;color:var(--muted);font-size:13px}.project-table-scroll{overflow-x:auto}.project-model-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.project-model-card{display:grid;align-content:start;gap:9px;padding:15px;border:1px solid var(--line);border-radius:9px}.project-model-title{display:flex;align-items:center;gap:9px}.project-model-title span{padding:6px;border-radius:5px;background:#243c50;color:#fff;font-size:10px}.project-model-title button{border:0;background:transparent;color:var(--ink);font-weight:700;text-align:left;cursor:pointer}.project-model-card p{margin:0;color:var(--ink);font-size:12px}.project-model-card small{color:var(--muted)}.project-type-summary{color:var(--muted);font-size:12px}.project-file-table{min-width:660px;border:1px solid var(--line);border-radius:8px;overflow:hidden}.project-file-row{box-sizing:border-box;width:100%;display:grid;grid-template-columns:minmax(190px,2fr) 90px 90px minmax(120px,1fr) 150px;gap:10px;align-items:center;padding:11px 13px;border:0;border-top:1px solid var(--line);background:var(--panel);color:var(--ink);text-align:left;font:inherit;font-size:12px;cursor:pointer}.project-file-row.heading{border-top:0;background:color-mix(in srgb,var(--panel) 94%,var(--ink));color:var(--muted);font-weight:700;cursor:default}.project-file-row b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.project-file-row small{color:var(--muted)}.project-preview-note{margin:10px 0 0;color:var(--muted);font-size:12px}@media(max-width:800px){.project-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.project-head{display:grid;gap:12px}.project-picker{width:100%}.project-picker-trigger{width:100%}.project-section-head{display:block}.project-section-head>span{display:block;margin-top:8px}.project-module{padding:16px}.project-module-head{align-items:flex-start;flex-wrap:wrap}}@media(max-width:430px){.project-stat-grid{gap:7px}.project-stat-grid article{padding:12px}.project-stat-grid small{font-size:11px}.project-stat-grid b{font-size:23px}}
.project-dataset-table{min-width:900px;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.project-dataset-row{box-sizing:border-box;width:100%;display:grid;grid-template-columns:minmax(180px,2fr) 95px repeat(5,minmax(65px,1fr)) 145px;align-items:center;gap:8px;padding:11px 14px;border:0;border-top:1px solid var(--line);background:var(--panel);color:var(--ink);text-align:left;font:inherit;font-size:12px}
button.project-dataset-row{cursor:pointer}
.project-dataset-row.heading{border-top:0;background:color-mix(in srgb,var(--panel) 94%,var(--ink));color:var(--muted);font-weight:700}
.project-dataset-row.total{background:var(--accent-soft);font-weight:700}
.project-dataset-row small{color:var(--muted)}
.project-sections,.project-empty{margin-top:24px}
.project-head,.project-picker{min-width:0}.project-picker{max-width:100%}.project-picker-trigger{max-width:min(420px,100%);min-width:0}.project-picker-label{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.project-picker-options label{overflow-wrap:anywhere}.project-picker-options input{flex-shrink:0}
.project-model-parameters{display:flex;flex-wrap:wrap;gap:6px}.project-model-parameters span{max-width:100%;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--accent-soft);color:var(--ink);font-size:12px;overflow-wrap:anywhere}.project-model-parameters b{font-weight:700}
</style>
