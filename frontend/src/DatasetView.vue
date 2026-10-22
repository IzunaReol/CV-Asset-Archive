<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from './api'
import { useDialogAccessibility } from './dialogAccessibility'
import ModelParametersDialog from './components/ModelParametersDialog.vue'

type DemoState = 'normal' | 'loading' | 'empty' | 'error' | 'forbidden'
type DatasetTab = 'overview' | 'members' | 'versions' | 'models'
type DatasetDraft = { mode:'create'|'edit'; datasetId:string; form:{name:string;remark:string;status:string;projects:string[]} }

type DatasetRow = {
  id:string; name:string; remark:string; version:string; members:number; size:string;
  status:string; projects:string[]; created:string; updated:string; creator:string;
  counts:{image:number;video:number;annotation:number;archive:number;other:number}
}

const props = withDefaults(defineProps<{statusValues?:string[];projectValues?:string[];filterDefinitions?:any[];openRequest?:{id:string;nonce:number}|null;listRequestNonce?:number;resumeDraft?:DatasetDraft|null;canCreateEdit?:boolean;canManageMembers?:boolean;canPublishVersion?:boolean;canRestoreVersion?:boolean;canDelete?:boolean;canManageModels?:boolean;canEditModelParameters?:boolean;canExport?:boolean;canManageProjects?:boolean}>(), {statusValues:()=>['待整理','未标注','已标注','审核中','待复核','已训练'],projectValues:()=>[],filterDefinitions:()=>[],openRequest:null,listRequestNonce:0,resumeDraft:null,canCreateEdit:false,canManageMembers:false,canPublishVersion:false,canRestoreVersion:false,canDelete:false,canManageModels:false,canEditModelParameters:false,canExport:false,canManageProjects:false})
const emit = defineEmits<{ notify:[message:string, kind?:'success'|'error']; export:[dataset:{name:string;members:number}]; addProject:[draft:DatasetDraft]; resumed:[] }>()
const view = ref<'list'|'detail'>('list')
const activeTab = ref<DatasetTab>('overview')
const demoState = ref<DemoState>('normal')
const query = ref('')
const statusFilter = ref('')
const creatorFilter = ref('')
const updatedFilter = ref('')
const pageSize = ref(50)
const page = ref(1)
const total = ref(0)
const creators = ref<string[]>([])
const memberPage = ref(1)
const memberPageSize = ref(50)
const memberTotal = ref(0)
const copyTarget = ref<DatasetRow|null>(null)
const copyAssets = ref(false)
const copyName = ref('')
const copyBusy = ref(false)
const selectedMemberIds = ref<string[]>([])
const operationBusy=ref(false)
const pickerMode=ref<'add'|'filter'>('add')
const memberFilters=ref(new URLSearchParams())
const candidateNames=ref<Record<string,string>>({})
const versionDetail=ref<any>(null)
const memberRenderLimit=ref(200)
const candidateRenderLimit=ref(200)
const datasetRenderLimit=ref(200)
const versionDetailPage=ref(1)
const versionDetailLoading=ref(false)
const createOpen = ref(false)
const editOpen = ref(false)
const publishOpen = ref(false)
const compareOpen = ref(false)
const addMembersOpen = ref(false)
const confirmOpen = ref(false)
const confirmText = ref('')
const confirmAction = ref<null|(()=>void)>(null)
const form = ref({name:'',remark:'',status:'',projects:[] as string[]})
const releaseNote = ref('')
const versionDraft = ref('v1')
const compareFrom = ref('v1')
const compareTo = ref('v3')
const candidatePage=ref(1)
const candidatePageSize=ref(50)
const candidateTotal=ref(0)
let appliedCandidateParams=new URLSearchParams()
const candidateQuery = ref('')
const candidateType = ref('')
const candidateSelected = ref<string[]>([])
const candidateSelectionId = ref('')
const candidateExcludedIds = ref<string[]>([])
const existingCandidateIds = ref<string[]>([])
const candidateLoading = ref(false)
let candidateFilterTimer: ReturnType<typeof setTimeout>|undefined
const candidateNoTags = ref(false)
const candidateMatch = ref<'all'|'any'>('all')
const candidateRules = ref<Array<{id:number;tag:string;operator:string;value:string;valueEnd?:string}>>([])
let nextCandidateRuleId=1
const modelOpen = ref(false)
const modelCandidates = ref<any[]>([])
const selectedModelId = ref('')
const selectedVersionId = ref('')
const modelRelationRemark = ref('')
const editingModel = ref<any>(null)
const modelParameterTarget = ref<any>(null)
const editingModelRemark = ref('')
const expandedDiffGroup = ref('图片')

const datasets = ref<DatasetRow[]>([])
let requestedDatasetGeneration = 0
const activeDataset = ref<DatasetRow>({id:'',name:'',remark:'',version:'—',members:0,size:'0 B',status:'待整理',projects:[],created:'',updated:'',creator:'',counts:{image:0,video:0,annotation:0,archive:0,other:0}})

const members = ref<any[]>([])

const versions = ref<any[]>([])

const models = ref<any[]>([])
const tagDistribution = ref<Array<[string,number]>>([])
const diffGroups = ref<any[]>([])
const diffStats = ref({added:0,removed:0,unchanged:0,total_changed:0})
const diffTruncated = ref(false)

const candidates = ref<any[]>([])

const filteredDatasets = computed(() => datasets.value)
const filteredCandidates = computed(() => candidates.value.filter(item=>item.rawType!=='annotation'))
const allMembersSelected = computed(() => members.value.some(item=>item.rawType!=='annotation') && members.value.filter(item=>item.rawType!=='annotation').every(item=>selectedMemberIds.value.includes(item.id)))

const typeLabels:Record<string,string>={image:'图片',video:'视频',annotation:'标注',archive:'压缩文件',other:'其他'}
function formatBytes(value:number) { if(!value)return '0 B'; const units=['B','KB','MB','GB','TB']; const index=Math.min(Math.floor(Math.log(value)/Math.log(1024)),units.length-1); return `${(value/1024**index).toFixed(index>1?1:0)} ${units[index]}` }
function formatDate(value:string) { return value ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '—' }
function mapDataset(item:any):DatasetRow { return {id:item.id,name:item.name,remark:item.remark||'',version:item.current_version||'—',members:item.member_count||0,size:formatBytes(item.total_size||0),status:item.status||'待整理',projects:Array.isArray(item.projects)?item.projects:[],created:formatDate(item.created_at),updated:formatDate(item.updated_at),creator:item.created_by_name||item.created_by||'—',counts:{image:item.counts?.image||0,video:item.counts?.video||0,annotation:item.counts?.annotation||0,archive:item.counts?.archive||0,other:item.counts?.other||0}} }
function mapAsset(item:any) { return {id:String(item.id),rawType:item.type,type:typeLabels[item.type]||'其他',name:item.name,remark:item.remark||'',tags:Object.values(item.tags||{}).flatMap((value:any)=>Array.isArray(value)?value:[value]).filter(Boolean),rawTags:item.tags||{},size:formatBytes(item.size||0),preview_url:item.preview_url||null,has_annotation:!!item.has_annotation} }
function tagStyle(value:string){const palette=['#2764c6','#16a34a','#d95c35','#7c3aed','#0891b2','#ca8a04','#db2777','#475569'];let hash=0;for(const char of value)hash=(hash*31+char.charCodeAt(0))>>>0;const color=palette[hash%palette.length];return {color,background:`color-mix(in srgb, ${color} 14%, var(--panel))`,borderColor:`color-mix(in srgb, ${color} 35%, transparent)`}}
async function loadDatasets() { demoState.value='loading'; try { const params=new URLSearchParams(); if(query.value.trim())params.set('q',query.value.trim());if(statusFilter.value)params.set('status',statusFilter.value);if(creatorFilter.value)params.set('creator',creatorFilter.value);if(updatedFilter.value)params.set('updated_from',updatedFilter.value);params.set('page',String(page.value));params.set('page_size',String(pageSize.value));const result=await api.datasets(params);datasets.value=result.items.map(mapDataset);datasetRenderLimit.value=200;total.value=result.total;demoState.value='normal' } catch(error) { demoState.value='error';emit('notify',error instanceof Error?error.message:'数据集加载失败','error') } }
function returnToList() { requestedDatasetGeneration++; view.value='list'; void loadDatasets() }
async function loadDatasetContent() { const [memberResult,versionResult,modelResult]=await Promise.all([api.datasetMembers(activeDataset.value.id,memberPage.value,memberPageSize.value,memberFilters.value),api.datasetVersions(activeDataset.value.id),api.datasetModels(activeDataset.value.id)]);members.value=memberResult.items.map(mapAsset);memberRenderLimit.value=200;memberTotal.value=memberResult.total;tagDistribution.value=(await api.datasetTagDistribution(activeDataset.value.id)).items;versions.value=versionResult.items.map((item:any)=>({id:item.id,version:item.version,note:item.release_note||'—',members:item.member_count,size:formatBytes(item.total_size),creator:item.created_by_name||item.created_by,created:formatDate(item.created_at),models:modelResult.items.filter((entry:any)=>entry.version?.id===item.id).length}));models.value=modelResult.items.filter((entry:any)=>entry.model).map((entry:any)=>({id:entry.model.id,relationId:entry.relation.id,name:entry.model.name,remark:entry.relation.provenance?.remark||'',version:entry.version?.version||'—',updated:formatDate(entry.model.updated_at),parameters:entry.configured_parameters||[]}));compareFrom.value=versions.value.at(-1)?.id||'';compareTo.value=versions.value[0]?.id||'' }
async function openDataset(item:DatasetRow) { activeDataset.value=item; activeTab.value='overview';memberPage.value=1;memberFilters.value=new URLSearchParams();selectedMemberIds.value=[];view.value='detail';try{await loadDatasetContent()}catch(error){emit('notify',error instanceof Error?error.message:'数据集详情加载失败','error')} }
async function openRequestedDataset(id:string){const requestId=++requestedDatasetGeneration;try{const item=mapDataset(await api.dataset(id));if(requestId!==requestedDatasetGeneration)return;await openDataset(item);if(requestId===requestedDatasetGeneration)activeTab.value='members'}catch(error){if(requestId===requestedDatasetGeneration)emit('notify',error instanceof Error?error.message:'数据集详情加载失败','error')}}
function startCreate() { form.value={name:'',remark:'',status:props.statusValues[0]||'待整理',projects:[]}; createOpen.value=true }
async function createDataset() {
  if(!form.value.name.trim()||!form.value.projects.length) return
  if(operationBusy.value)return;operationBusy.value=true;try { const result=await api.createDataset({name:form.value.name.trim(),remark:form.value.remark,status:form.value.status||props.statusValues[0]||'待整理',projects:form.value.projects});const row=mapDataset(result);datasets.value.unshift(row);createOpen.value=false;emit('notify','数据集已创建');await openDataset(row) } catch(error){emit('notify',error instanceof Error?error.message:'数据集创建失败','error')}
finally{operationBusy.value=false} }
function startEdit() { form.value={name:activeDataset.value.name,remark:activeDataset.value.remark,status:activeDataset.value.status,projects:activeDataset.value.projects.filter(value=>props.projectValues.includes(value))}; editOpen.value=true }
function navigateToProjectEditor() { emit('addProject',{mode:editOpen.value?'edit':'create',datasetId:activeDataset.value.id,form:{...form.value,projects:[...form.value.projects]}}) }
async function saveEdit() { if(operationBusy.value||!form.value.projects.length)return;operationBusy.value=true;try { activeDataset.value=mapDataset(await api.updateDataset(activeDataset.value.id,{name:form.value.name.trim()||activeDataset.value.name,remark:form.value.remark,status:form.value.status||activeDataset.value.status,projects:form.value.projects}));datasets.value=datasets.value.map(item=>item.id===activeDataset.value.id?activeDataset.value:item);editOpen.value=false;emit('notify','数据集信息已更新') }catch(error){emit('notify',error instanceof Error?error.message:'数据集更新失败','error')} finally{operationBusy.value=false} }
function cloneDataset(item:DatasetRow) { copyTarget.value=item;copyAssets.value=false;copyName.value=`${item.name}副本` }
async function confirmCopy(){if(!copyTarget.value||copyBusy.value||!copyName.value.trim())return;copyBusy.value=true;try{await api.copyDataset(copyTarget.value.id,copyAssets.value,copyName.value.trim());copyTarget.value=null;await loadDatasets();emit('notify','数据集已复制')}catch(error){emit('notify',error instanceof Error?error.message:'数据集复制失败','error')}finally{copyBusy.value=false}}
async function loadMembers(){try{const result=await api.datasetMembers(activeDataset.value.id,memberPage.value,memberPageSize.value,memberFilters.value);members.value=result.items.map(mapAsset);memberRenderLimit.value=200;memberTotal.value=result.total}catch(error){emit('notify',error instanceof Error?error.message:'素材加载失败','error')}}
function localTime(date=new Date()){return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,19)}
function nextTime(value:string){return localTime(new Date(new Date(value).getTime()+1000))}
function isTime(key:string){return ['created_at','updated_at'].includes(key)}
function changeCandidateField(rule:any){rule.operator=isTime(rule.tag)?'equals':'contains';rule.value=isTime(rule.tag)?localTime():'';rule.valueEnd=nextTime(rule.value||localTime())}
function changeCandidateOperator(rule:any){if(rule.operator==='between')rule.valueEnd=nextTime(rule.value||localTime())}

function ask(text:string, action:()=>void|Promise<void>) { confirmText.value=text; confirmAction.value=action as ()=>void; confirmOpen.value=true }
async function runConfirm() { if(operationBusy.value)return;operationBusy.value=true;try{await confirmAction.value?.();confirmOpen.value=false;confirmAction.value=null}catch(error){emit('notify',error instanceof Error?error.message:'操作失败','error')}finally{operationBusy.value=false} }
function removeDataset(item:DatasetRow) { ask(`确定要删除“${item.name}”吗？历史版本和模型关联将一并清除，素材文件保留。`,async()=>{await api.deleteDataset(item.id);if(pageSize.value&&page.value>1&&datasets.value.length===1)page.value--;await loadDatasets();emit('notify','数据集已删除')}) }
function toggleMember(id:string) { if(members.value.find(item=>item.id===id)?.rawType==='annotation')return;selectedMemberIds.value=selectedMemberIds.value.includes(id)?selectedMemberIds.value.filter(item=>item!==id):[...selectedMemberIds.value,id] }
function selectAllMembers() { selectedMemberIds.value=[...new Set([...selectedMemberIds.value,...members.value.filter(item=>item.rawType!=='annotation').map(item=>item.id)])] }
function invertMembers() { const selectable=members.value.filter(item=>item.rawType!=='annotation');selectedMemberIds.value=[...selectedMemberIds.value.filter(id=>!selectable.some(item=>item.id===id)),...selectable.filter(item=>!selectedMemberIds.value.includes(item.id)).map(item=>item.id)] }
async function removeMembers() { const ids=[...selectedMemberIds.value];const body={asset_ids:ids};try{const preview=await api.previewDatasetMembers(activeDataset.value.id,body,'remove');if(preview.invalid_ids.length){emit('notify','标注不能单独移出数据集','error');return}ask(`确定移除 ${preview.asset_ids.length} 项素材以及 ${preview.annotations.removed.length} 项关联标注吗？`,async()=>{await api.removeDatasetMembers(activeDataset.value.id,body);selectedMemberIds.value=[];memberFilters.value=new URLSearchParams();memberPage.value=1;await refreshActiveDataset();emit('notify','已从数据集移出')})}catch(error){emit('notify',error instanceof Error?error.message:'预览失败','error')} }
function toggleCandidate(id:string) { if(candidates.value.find(item=>item.id===id)?.rawType==='annotation'||(pickerMode.value==='add'&&existingCandidateIds.value.includes(id)))return;if(candidateSelectionId.value){candidateExcludedIds.value=candidateExcludedIds.value.includes(id)?candidateExcludedIds.value.filter(item=>item!==id):[...candidateExcludedIds.value,id];return}candidateSelected.value=candidateSelected.value.includes(id)?candidateSelected.value.filter(item=>item!==id):[...candidateSelected.value,id] }
function addCandidateRule(){candidateRules.value.push({id:nextCandidateRuleId++,tag:props.filterDefinitions[0]?.key||'remark',operator:'contains',value:''})}
function candidateParams(){const params=new URLSearchParams({match:candidateMatch.value});if(candidateQuery.value.trim())params.set('q',candidateQuery.value.trim());if(candidateType.value)params.append('asset_type',candidateType.value);else Object.keys(typeLabels).filter(type=>type!=='annotation').forEach(type=>params.append('asset_type',type));if(candidateNoTags.value)params.set('no_tags','true');candidateRules.value.filter(rule=>rule.value.trim()).forEach(rule=>{let value=rule.value;if(isTime(rule.tag)){value=new Date(rule.value).toISOString();if(rule.operator==='between'){if(!rule.valueEnd||new Date(rule.valueEnd)<=new Date(rule.value))throw new Error('结束时间必须晚于开始时间');value+='|'+new Date(rule.valueEnd).toISOString()}}params.append('tag',`${rule.tag}:${rule.operator}:${value}`)});return params}
async function loadCandidates(){try{appliedCandidateParams=candidateParams();candidatePage.value=1;candidateSelected.value=[];candidateSelectionId.value='';candidateExcludedIds.value=[];await fetchCandidatePage()}catch(error){emit('notify',error instanceof Error?error.message:'素材加载失败','error')}}
async function fetchCandidatePage(){candidateLoading.value=true;try{const params=new URLSearchParams(appliedCandidateParams);params.set('page',String(candidatePage.value));params.set('page_size',String(candidatePageSize.value||200));const result=pickerMode.value==='filter'?await api.datasetMembers(activeDataset.value.id,candidatePage.value,candidatePageSize.value||200,appliedCandidateParams):await api.assets(params);candidateTotal.value=result.total;const items=result.items;candidates.value=items.map(mapAsset);candidateRenderLimit.value=200;items.forEach((item:any)=>candidateNames.value[item.id]=item.name);existingCandidateIds.value=pickerMode.value==='add'&&items.length?(await api.datasetMemberStatus(activeDataset.value.id,items.map((item:any)=>item.id))).existing_ids:[]}catch(error){emit('notify',error instanceof Error?error.message:'素材加载失败','error')}finally{candidateLoading.value=false}}
async function openMemberPicker(mode:'add'|'filter'='add'){pickerMode.value=mode;addMembersOpen.value=true;candidateSelected.value=[];candidateRules.value=[];candidateQuery.value='';candidateType.value='';candidateNoTags.value=false;candidateMatch.value='all';await loadCandidates()}
async function openMemberFilter(){await openMemberPicker('filter')}
async function applyMemberFilter(){try{memberFilters.value=new URLSearchParams(appliedCandidateParams);memberPage.value=1;await loadMembers();selectedMemberIds.value=[...candidateSelected.value];addMembersOpen.value=false}catch(error){emit('notify',error instanceof Error?error.message:'筛选失败','error')}}
watch([candidateQuery,candidateType,candidateNoTags,candidateMatch,candidateRules],()=>{if(!addMembersOpen.value)return;clearTimeout(candidateFilterTimer);candidateFilterTimer=setTimeout(()=>{void loadCandidates()},300)},{deep:true})
function selectCandidatePage(){candidateSelected.value=[...new Set([...candidateSelected.value,...candidates.value.filter(item=>item.rawType!=='annotation'&&(pickerMode.value!=='add'||!existingCandidateIds.value.includes(item.id))).map(item=>item.id)])]}
function invertCandidatePage(){const selectable=candidates.value.filter(item=>item.rawType!=='annotation'&&(pickerMode.value!=='add'||!existingCandidateIds.value.includes(item.id)));candidateSelected.value=[...candidateSelected.value.filter(id=>!selectable.some(item=>item.id===id)),...selectable.filter(item=>!candidateSelected.value.includes(item.id)).map(item=>item.id)]}
function clearCandidateSelection(){candidateSelected.value=[];candidateSelectionId.value='';candidateExcludedIds.value=[]}
async function selectAllCandidates(){const params=appliedCandidateParams;const result=await api.createAssetSelection({q:params.get('q')||'',no_tags:params.get('no_tags')==='true',asset_type:params.getAll('asset_type'),match:params.get('match')||'all',tag:params.getAll('tag')});candidateSelectionId.value=result.selection_id;candidateSelected.value=[];candidateExcludedIds.value=[]}
async function openVersionDetail(version:any){try{versionDetailPage.value=1;versionDetail.value=await api.datasetVersion(activeDataset.value.id,version.id,1,200)}catch(error){emit('notify',error instanceof Error?error.message:'版本加载失败','error')}}
async function loadMoreVersionMembers(){if(!versionDetail.value||versionDetailLoading.value)return;versionDetailLoading.value=true;try{const nextPage=versionDetailPage.value+1;const result=await api.datasetVersion(activeDataset.value.id,versionDetail.value.id,nextPage,200);versionDetail.value={...versionDetail.value,members:[...versionDetail.value.members,...result.members]};versionDetailPage.value=nextPage}catch(error){emit('notify',error instanceof Error?error.message:'版本成员加载失败','error')}finally{versionDetailLoading.value=false}}
async function refreshActiveDataset(){activeDataset.value=mapDataset(await api.dataset(activeDataset.value.id));datasets.value=datasets.value.map(item=>item.id===activeDataset.value.id?activeDataset.value:item);await loadDatasetContent()}
async function addMembers() { if(operationBusy.value)return;const body=candidateSelectionId.value?{selection_id:candidateSelectionId.value,excluded_ids:candidateExcludedIds.value}:{asset_ids:[...candidateSelected.value]};try{const preview=await api.previewDatasetMembers(activeDataset.value.id,body,'add');if(preview.invalid_ids.length){emit('notify','选择中包含不可加入的素材','error');return}if(!preview.asset_ids.length){emit('notify','所选素材已在数据集中，无需重复加入','error');return}ask(`确定将 ${preview.asset_ids.length} 项素材以及 ${preview.annotations.added.length} 项关联标注加入数据集中吗？`,async()=>{const result=await api.addDatasetMembers(activeDataset.value.id,body);clearCandidateSelection();addMembersOpen.value=false;await refreshActiveDataset();emit('notify',`已添加 ${result.added} 项素材`)})}catch(error){emit('notify',error instanceof Error?error.message:'添加素材预览失败','error')} }
async function publishVersion() { if(operationBusy.value)return;operationBusy.value=true;try{const result=await api.publishDatasetVersion(activeDataset.value.id,versionDraft.value.trim(),releaseNote.value.trim());releaseNote.value='';publishOpen.value=false;activeTab.value='versions';await refreshActiveDataset();emit('notify',`${result.version} 已发布`)}catch(error){emit('notify',error instanceof Error?error.message:'版本发布失败','error')} finally{operationBusy.value=false} }
function openPublish(){versionDraft.value=`v${versions.value.length+1}`;releaseNote.value='';publishOpen.value=true}
let modelPickerGeneration = 0
async function openModelPicker(){
  if(!versions.value.length){emit('notify','请先发布数据集版本','error');return}
  const generation=++modelPickerGeneration
  selectedVersionId.value=versions.value[0].id;selectedModelId.value='';modelRelationRemark.value='';autoFilledModelRemark='';modelCandidates.value=[];modelOpen.value=true
  try{
    let pageNumber=1
    let loaded=0
    let total=1
    while(loaded<total){
      const result=await api.assets(new URLSearchParams({page:String(pageNumber++),page_size:'200',asset_type:'model'}))
      if(generation!==modelPickerGeneration||!modelOpen.value)return
      if(!result.items.length)break
      loaded+=result.items.length;total=result.total
      modelCandidates.value=[...modelCandidates.value,...result.items.filter((item:any)=>!modelCandidates.value.some((existing:any)=>existing.id===item.id))]
    }
  }catch(error){if(generation===modelPickerGeneration&&modelOpen.value)emit('notify',error instanceof Error?error.message:'模型加载失败','error')}
}
let autoFilledModelRemark = ''
function selectModelCandidate(){
  const model=modelCandidates.value.find((item:any)=>item.id===selectedModelId.value)
  const remark=String(model?.remark||'').trim()
  if(remark){modelRelationRemark.value=remark;autoFilledModelRemark=remark}
  else if(modelRelationRemark.value===autoFilledModelRemark){modelRelationRemark.value='';autoFilledModelRemark=''}
}
async function addModelRelation(){if(!selectedModelId.value||!selectedVersionId.value)return;if(operationBusy.value)return;const model=modelCandidates.value.find((item:any)=>item.id===selectedModelId.value);const version=versions.value.find((item:any)=>item.id===selectedVersionId.value);ask(`确定将“${model?.name||'模型'}”关联至 ${version?.version||'所选版本'} 吗？该版本包含 ${version?.members||0} 项素材。`,async()=>{const result=await api.addDatasetModel(activeDataset.value.id,{model_id:selectedModelId.value,version_id:selectedVersionId.value,remark:modelRelationRemark.value.trim()});modelOpen.value=false;await loadDatasetContent();emit('notify',result.created?'模型与数据集版本已关联':'该关联已存在')}) }
function editModelRelation(model:any){editingModel.value=model;editingModelRemark.value=model.remark}
async function saveModelRelationRemark(){if(!editingModel.value||operationBusy.value)return;operationBusy.value=true;try{await api.updateDatasetModelRemark(activeDataset.value.id,editingModel.value.relationId,editingModelRemark.value.trim());editingModel.value=null;await loadDatasetContent();emit('notify','关联备注已更新')}catch(error){emit('notify',error instanceof Error?error.message:'关联备注更新失败','error')}finally{operationBusy.value=false}}
function removeModelRelation(model:any){ask(`确定删除“${model.name}”与该数据集版本的全部关联吗？`,async()=>{const result=await api.removeDatasetModel(activeDataset.value.id,model.relationId);await loadDatasetContent();emit('notify',`已取消 ${result.revoked} 条关联关系`)})}
async function loadVersionCompare(){if(!compareOpen.value||!compareFrom.value||!compareTo.value||compareFrom.value===compareTo.value)return;try{const result=await api.compareDatasetVersions(activeDataset.value.id,compareFrom.value,compareTo.value);diffStats.value=result.counts;diffTruncated.value=Boolean(result.truncated);const grouped:Record<string,any>={};const add=(type:string,action:string,name:string)=>{const label=typeLabels[type]||'其他';const group=grouped[label]||={type:label,count:0,added:0,removed:0,changed:0,items:[]};group.count+=1;if(action==='新增')group.added+=1;else if(action==='移除')group.removed+=1;else group.changed+=1;group.items.push([action,name])};result.added.forEach((item:any)=>add(item.snapshot.type,'新增',item.snapshot.name));result.removed.forEach((item:any)=>add(item.snapshot.type,'移除',item.snapshot.name));result.changed.forEach((item:any)=>add(item.after.type,'信息变化',item.after.name));diffGroups.value=Object.values(grouped);expandedDiffGroup.value=diffGroups.value[0]?.type||''}catch(error){emit('notify',error instanceof Error?error.message:'版本对比加载失败','error')}}
function restoreVersion(version:any) { ask(`确定将 ${version.version} 的数据恢复到当前数据集吗？`,async()=>{await api.restoreDatasetVersion(activeDataset.value.id,version.id);activeTab.value='members';await refreshActiveDataset();emit('notify',`${version.version} 已恢复到数据集`)}) }
function exportDataset() { ask('将按照当前数据集进行导出，确定要导出吗？',async()=>{await api.exportDataset(activeDataset.value.id);emit('export',{name:activeDataset.value.name,members:activeDataset.value.members});emit('notify','数据集导出任务已加入任务中心')}) }
const openDialogCount = computed(() => [createOpen.value,editOpen.value,publishOpen.value,compareOpen.value,copyTarget.value,addMembersOpen.value,modelOpen.value,editingModel.value,modelParameterTarget.value,versionDetail.value,confirmOpen.value].filter(Boolean).length)
function closeTopDialog(){
  if(confirmOpen.value&&!operationBusy.value){confirmOpen.value=false;confirmAction.value=null;return}
  if(modelParameterTarget.value){modelParameterTarget.value=null;return}
  if(versionDetail.value){versionDetail.value=null;return}
  if(editingModel.value&&!operationBusy.value){editingModel.value=null;return}
  if(modelOpen.value&&!operationBusy.value){modelOpen.value=false;return}
  if(addMembersOpen.value&&!candidateLoading.value){addMembersOpen.value=false;return}
  if(copyTarget.value&&!copyBusy.value){copyTarget.value=null;return}
  if(compareOpen.value){compareOpen.value=false;return}
  if(publishOpen.value&&!operationBusy.value){publishOpen.value=false;return}
  if((createOpen.value||editOpen.value)&&!operationBusy.value){createOpen.value=false;editOpen.value=false}
}
useDialogAccessibility(openDialogCount,closeTopDialog)
watch([query,statusFilter,creatorFilter,updatedFilter,pageSize],()=>{page.value=1;if(view.value==='list')void loadDatasets()})
watch(page,()=>{if(view.value==='list')void loadDatasets()})
watch(memberPage,()=>void loadMembers())
watch(memberPageSize,()=>{memberPage.value=1;void loadMembers()})
watch([compareOpen,compareFrom,compareTo],()=>void loadVersionCompare())
watch(()=>props.openRequest?.nonce,()=>{if(props.openRequest?.id)void openRequestedDataset(props.openRequest.id)})
watch(()=>props.listRequestNonce,()=>{if(!props.openRequest?.id) returnToList()})
onMounted(()=>{
  void api.datasetCreators().then(result=>creators.value=result.items).catch(()=>{})
  if(props.resumeDraft){
    const draft=props.resumeDraft
    void (async()=>{
      if(draft.mode==='edit' && draft.datasetId){await openRequestedDataset(draft.datasetId);startEdit()}
      else {void loadDatasets();startCreate()}
      form.value={...draft.form,projects:draft.form.projects.filter(value=>props.projectValues.includes(value))}
      emit('resumed')
    })()
  } else if(props.openRequest?.id)void openRequestedDataset(props.openRequest.id)
  else void loadDatasets()
})
</script>

<template>
  <template v-if="view==='list'">
    <section class="page-head dataset-head"><div><h1>数据集</h1></div><button v-if="props.canCreateEdit" class="primary" @click="startCreate">＋ 新建数据集</button></section>
    <section class="dataset-filters">
      <input v-model="query" placeholder="搜索名称或备注" />
      <select v-model="statusFilter"><option value="">全部状态</option><option v-for="value in props.statusValues" :key="value" :value="value">{{value}}</option></select>
      <select v-model="creatorFilter"><option value="">全部创建人</option><option v-for="creator in creators" :key="creator" :value="creator">{{creator}}</option></select>
      <input v-model="updatedFilter" type="date" aria-label="更新时间" />
      <button @click="query='';statusFilter='';creatorFilter='';updatedFilter=''">重置</button>
    </section>
    <section v-if="demoState==='loading'" class="state-panel"><div class="spinner"></div><b>正在加载数据集</b></section>
    <section v-else-if="demoState==='error'" class="state-panel error-state"><span>!</span><b>数据集加载失败</b><button @click="loadDatasets">重新加载</button></section>
    <section v-else-if="demoState==='forbidden'" class="state-panel"><span>⌾</span><b>没有查看权限</b></section>
    <section v-else-if="demoState==='empty'||!filteredDatasets.length" class="empty"><b>暂无数据集</b><p>选择素材后可以创建第一个数据集。</p><button v-if="props.canCreateEdit" class="primary" @click="startCreate">新建数据集</button></section>
    <section v-else class="dataset-table-wrap">
      <div class="dataset-table">
        <div class="dataset-row head"><span>数据集</span><span>当前版本</span><span>数据数量</span><span>素材构成</span><span>总容量</span><span>状态</span><span>创建时间</span><span>最近修改</span><span>创建人</span><span>操作</span></div>
        <div v-for="item in filteredDatasets.slice(0,datasetRenderLimit)" :key="item.id" class="dataset-row">
          <button class="dataset-name" @click="openDataset(item)"><b :title="item.name">{{item.name}}</b><small :title="item.remark">{{item.remark}}</small></button>
          <b>{{item.version}}</b><span>{{item.members.toLocaleString()}} 项</span>
          <span class="dataset-counts" :title="`图片 ${item.counts.image}、视频 ${item.counts.video}、标注 ${item.counts.annotation}、压缩文件 ${item.counts.archive}`">图片 {{item.counts.image}} · 视频 {{item.counts.video}} · 标注 {{item.counts.annotation}} · 压缩文件 {{item.counts.archive}}</span>
          <span>{{item.size}}</span><span><i class="dataset-status" :style="tagStyle(item.status)">{{item.status}}</i></span><span class="dataset-date">{{item.created}}</span><span class="dataset-date">{{item.updated}}</span><span>{{item.creator}}</span>
          <span class="dataset-actions"><button @click="openDataset(item)">详情</button><button v-if="props.canCreateEdit" @click="cloneDataset(item)">复制</button><button v-if="props.canDelete" class="danger-inline" @click="removeDataset(item)">删除</button></span>
        </div>
      </div>
      <button v-if="datasets.length>datasetRenderLimit" @click="datasetRenderLimit+=200">继续显示</button><div class="pagination dataset-pagination"><span>当前页 {{filteredDatasets.length}} 项 · 全部 {{total}} 项</span><div class="page-controls"><label>每页 <select v-model="pageSize"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option><option :value="0">全部</option></select> 项</label><button :disabled="page<=1||!pageSize" @click="page--">‹</button><span>{{page}}</span><button :disabled="!pageSize||page*pageSize>=total" @click="page++">›</button></div></div>
    </section>
  </template>

  <template v-else>
    <section class="dataset-detail-head">
      <button class="back-button" @click="returnToList">‹ 返回数据集</button>
      <div class="dataset-title"><div><h1>{{activeDataset.name}}</h1><p>所属项目：{{activeDataset.projects.length?activeDataset.projects.join('、'):'未设置'}}</p><p>{{activeDataset.remark||'暂无备注'}}</p></div><span class="dataset-status" :style="tagStyle(activeDataset.status)">{{activeDataset.status}}</span></div>
      <div class="dataset-detail-actions"><button v-if="props.canExport" class="secondary" @click="exportDataset">导出</button><button v-if="props.canCreateEdit" class="secondary" @click="startEdit">编辑</button><button class="secondary" @click="compareOpen=true">版本对比</button></div>
    </section>
    <section class="dataset-summary">
      <div><small>当前版本</small><b>{{activeDataset.version}}</b></div><div><small>数据数量</small><b>{{activeDataset.members.toLocaleString()}} 项</b></div><div><small>总容量</small><b>{{activeDataset.size}}</b></div><div><small>创建人</small><b>{{activeDataset.creator}}</b></div><div><small>创建时间</small><b>{{activeDataset.created}}</b></div><div><small>最近修改</small><b>{{activeDataset.updated}}</b></div>
    </section>
    <nav class="dataset-tabs"><button :class="{active:activeTab==='overview'}" @click="activeTab='overview'">概览</button><button :class="{active:activeTab==='members'}" @click="activeTab='members'">数据管理</button><button :class="{active:activeTab==='versions'}" @click="activeTab='versions'">版本记录</button><button :class="{active:activeTab==='models'}" @click="activeTab='models'">模型管理</button></nav>

    <section v-if="activeTab==='overview'" class="dataset-overview">
      <article><h2>素材构成</h2><div class="type-bars"><div v-for="item in [{label:'图片',value:activeDataset.counts.image,color:'#4f8ef7'},{label:'视频',value:activeDataset.counts.video,color:'#8b6de8'},{label:'标注',value:activeDataset.counts.annotation,color:'#ef6f6c'},{label:'压缩文件',value:activeDataset.counts.archive,color:'#d69b38'}]" :key="item.label"><span>{{item.label}}</span><i><em :style="{width:`${Math.max(4,item.value/Math.max(activeDataset.members,1)*100)}%`,background:item.color}"></em></i><b>{{item.value.toLocaleString()}}</b></div></div></article>
      <article><h2>标签分布</h2><div v-if="tagDistribution.length" class="tag-cloud"><span v-for="item in tagDistribution" :key="item[0]" :style="tagStyle(item[0])">{{item[0]}} <b>{{item[1]}}</b></span></div><p v-else class="dataset-empty-text">暂无标签</p></article>
      <article class="dataset-activity"><h2>最近修改</h2><p class="dataset-empty-text">{{activeDataset.updated}}</p></article>
      <article><div class="overview-title"><h2>关联模型</h2><button v-if="models.length" class="link-button" @click="activeTab='models'">查看全部</button></div><div class="overview-model" v-for="model in models.slice(0,3)" :key="model.relationId"><b>{{model.name}}</b><span>{{model.version}}</span></div><p v-if="!models.length" class="dataset-empty-text">暂无关联模型</p></article>
    </section>

    <section v-else-if="activeTab==='members'" class="dataset-members-panel">
      <div class="member-toolbar"><div><button class="secondary" @click="openMemberFilter">筛选</button><button v-if="selectedMemberIds.length" class="secondary" @click="selectedMemberIds=[]">取消选择</button><button class="secondary" :disabled="allMembersSelected" @click="selectAllMembers">全选</button><button class="secondary" @click="invertMembers">反选</button></div><div v-if="props.canManageMembers"><button v-if="selectedMemberIds.length" class="danger-action" @click="removeMembers">移出数据集</button><button class="primary" @click="openMemberPicker()">＋ 添加素材</button></div></div>
      <div v-if="selectedMemberIds.length" class="batch-bar"><b>已选 {{selectedMemberIds.length}} 项</b><span>操作只影响当前数据集</span></div>
      <div class="member-grid"><article v-for="item in members.slice(0,memberRenderLimit)" :key="item.id" :class="{selected:selectedMemberIds.includes(item.id)}"><button class="member-select" @click="toggleMember(item.id)">{{selectedMemberIds.includes(item.id)?'✓':''}}</button><div class="member-preview"><img v-if="['图片','视频'].includes(item.type)&&item.preview_url" :src="item.preview_url" :alt="item.name" /><b v-else>{{item.type==='图片'?'IMG':item.type==='视频'?'VIDEO':'ARCHIVE'}}</b><i v-if="item.type==='视频'&&item.preview_url">▶</i></div><div><b :title="item.name">{{item.name}}</b><p :title="item.remark">{{item.remark}}</p><span :title="item.tags.join('、')"><i v-for="tag in item.tags" :key="tag" :style="tagStyle(tag)">{{tag}}</i></span><small>{{item.type}} · {{item.size}}<template v-if="item.has_annotation"> · <em class="annotation-badge">已关联标注</em></template></small></div></article></div>
      <button v-if="members.length>memberRenderLimit" @click="memberRenderLimit+=200">继续显示</button><div class="pagination dataset-pagination"><span>当前页 {{members.length}} 项 · 全部 {{memberTotal}} 项</span><div class="page-controls"><label>每页 <select v-model="memberPageSize"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option></select> 项</label><button :disabled="memberPage<=1" @click="memberPage--">‹</button><span>{{memberPage}}</span><button :disabled="memberPage*memberPageSize>=memberTotal" @click="memberPage++">›</button></div></div>
    </section>

    <section v-else-if="activeTab==='versions'" class="dataset-version-list">
      <div v-if="props.canPublishVersion" class="version-toolbar"><button class="primary" @click="openPublish">＋ 发布新版本</button></div>
      <div class="version-row head"><span>版本</span><span>发布说明</span><span>成员</span><span>容量</span><span>创建人</span><span>发布时间</span><span>关联模型</span><span>操作</span></div>
      <div v-for="item in versions" :key="item.version" class="version-row"><b>{{item.version}}</b><span :title="item.note">{{item.note}}</span><span>{{item.members.toLocaleString()}} 项</span><span>{{item.size}}</span><span>{{item.creator}}</span><span>{{item.created}}</span><span>{{item.models}} 个</span><span><button @click="openVersionDetail(item)">详情</button><button @click="compareFrom=item.id;compareOpen=true">对比</button><button v-if="props.canRestoreVersion" @click="restoreVersion(item)">恢复到数据集</button></span></div>
    </section>

    <section v-else class="dataset-models"><div v-if="props.canManageModels" class="model-toolbar"><button class="primary" @click="openModelPicker">＋ 添加模型关联</button></div><article v-for="model in models" :key="model.relationId"><div class="model-icon">MODEL</div><div class="model-summary"><b>{{model.name}}</b><span v-if="model.remark" :title="model.remark">{{model.remark}}</span><small class="model-version">关联数据集版本：{{model.version}}</small><small>最近修改 {{model.updated}}</small><div v-if="model.parameters.length" class="model-configured-parameters"><span v-for="parameter in model.parameters" :key="parameter.id" :title="parameter.category+' · '+parameter.name"><b>{{parameter.name}}</b>：{{parameter.value}}</span></div></div><div v-if="props.canManageModels||props.canEditModelParameters" class="model-relation-actions"><button v-if="props.canEditModelParameters" class="secondary" @click="modelParameterTarget=model">编辑参数</button><button v-if="props.canManageModels" class="secondary" @click="editModelRelation(model)">编辑备注</button><button v-if="props.canManageModels" class="danger-inline" @click="removeModelRelation(model)">删除关联</button></div></article><p v-if="!models.length" class="dataset-empty-text">暂无关联模型</p></section>
  </template>

  <div v-if="createOpen||editOpen" class="modal-stage"><section class="upload-dialog dataset-dialog">
    <button class="close" @click="createOpen=false;editOpen=false">×</button>
    <h2>{{editOpen?'编辑数据集':'新建数据集'}}</h2>
    <div class="form-stack">
      <label>数据集名称<input v-model="form.name" maxlength="100" placeholder="请输入名称" /></label>
      <div class="dataset-project-field">
        <div class="dataset-project-heading"><span>所属项目 <i>*</i></span><button type="button" :disabled="!props.canManageProjects" :title="props.canManageProjects?'前往标签管理添加项目':'当前账号无标签管理权限'" @click="navigateToProjectEditor">＋ 新增项目</button></div>
        <div v-if="props.projectValues.length" class="dataset-project-options" role="group" aria-label="所属项目">
          <label v-for="value in props.projectValues" :key="value"><input v-model="form.projects" type="checkbox" :value="value" />{{value}}</label>
        </div>
        <p v-else class="dataset-project-hint">暂无项目值，请先在标签管理中新增项目。</p>
        <small v-if="!form.projects.length" class="dataset-project-hint">请至少选择一个所属项目</small>
      </div>
      <label>备注<textarea v-model="form.remark" rows="4" maxlength="1000" placeholder="请输入备注" /></label>
      <label v-if="editOpen">状态<select v-model="form.status"><option v-for="value in props.statusValues" :key="value" :value="value">{{value}}</option></select></label>
    </div>
    <div class="dialog-actions"><button class="secondary" @click="createOpen=false;editOpen=false">取消</button><button class="primary" :disabled="operationBusy||!form.name.trim()||!form.projects.length" @click="editOpen?saveEdit():createDataset()">保存</button></div>
  </section></div>
  <div v-if="publishOpen" class="modal-stage"><section class="upload-dialog dataset-dialog publish-dialog"><button class="close" @click="publishOpen=false">×</button><h2>发布新版本</h2><div class="publish-form"><label>版本号<input v-model="versionDraft" maxlength="32" placeholder="例如 v1.1" /></label><label>数据数量<input :value="`${activeDataset.members.toLocaleString()} 项`" disabled /></label><label class="release-note-field">发布说明<textarea v-model="releaseNote" rows="5" maxlength="2000" placeholder="请输入本次版本的主要变化" /></label></div><p class="dialog-tip">发布后版本及其数据不可修改。</p><div class="dialog-actions"><button class="secondary" @click="publishOpen=false">取消</button><button class="primary" :disabled="operationBusy||!versionDraft.trim()" @click="publishVersion">确认发布</button></div></section></div>
  <div v-if="compareOpen" class="modal-stage"><section class="upload-dialog dataset-dialog compare-dialog"><button class="close" @click="compareOpen=false">×</button><h2>版本对比</h2><div class="compare-selectors"><label>基准版本<select v-model="compareFrom"><option v-for="item in versions" :key="item.version" :value="item.id">{{item.version}}</option></select></label><span>与</span><label>目标版本<select v-model="compareTo"><option v-for="item in versions" :key="item.version" :value="item.id">{{item.version}}</option></select></label></div><div class="compare-stats"><button class="added"><b>↑ {{diffStats.added.toLocaleString()}}</b><span>新增素材</span></button><button class="removed"><b>↓ {{diffStats.removed.toLocaleString()}}</b><span>移除素材</span></button><button class="unchanged"><b>{{diffStats.unchanged.toLocaleString()}}</b><span>未改动素材</span></button><button class="changed"><b>{{diffStats.total_changed.toLocaleString()}}</b><span>总改动数量</span></button></div><p v-if="diffTruncated" class="dialog-tip">变更数量较多，统计结果为全部数据，明细仅展示前 1000 项。</p><div class="compare-groups"><section v-for="group in diffGroups" :key="group.type"><button @click="expandedDiffGroup=expandedDiffGroup===group.type?'':group.type"><span><b>{{group.type}}</b><small>当前明细 {{group.count.toLocaleString()}} 项 · 新增 {{group.added}} · 移除 {{group.removed}} · 修改 {{group.changed}}</small></span><i>{{expandedDiffGroup===group.type?'⌃':'⌄'}}</i></button><div v-if="expandedDiffGroup===group.type" class="compare-group-items"><div v-for="item in group.items" :key="item[0]+item[1]"><em :class="item[0]" :style="tagStyle(item[0])">{{item[0]}}</em><b :title="item[1]">{{item[1]}}</b></div></div></section></div><div class="dialog-actions"><button class="primary" @click="compareOpen=false">关闭</button></div></section></div>
  <div v-if="copyTarget" class="modal-stage"><section class="upload-dialog dataset-dialog copy-dialog" role="dialog" aria-modal="true" aria-labelledby="copy-title"><button class="close" aria-label="关闭复制弹窗" :disabled="copyBusy" @click="copyTarget=null">×</button><h2 id="copy-title">复制数据集</h2><div class="copy-form"><label>数据集名称<input v-model="copyName" maxlength="100" placeholder="请输入数据集名称" :disabled="copyBusy" @keyup.enter="confirmCopy" /></label><label>复制范围<select v-model="copyAssets" :disabled="copyBusy"><option :value="false">只复制数据集</option><option :value="true">复制数据集加素材</option></select></label></div><div class="dialog-actions"><button class="secondary" :disabled="copyBusy" @click="copyTarget=null">取消</button><button class="primary" :disabled="copyBusy||!copyName.trim()" @click="confirmCopy">{{copyBusy?'正在复制':'确认复制'}}</button></div></section></div>
  <div v-if="addMembersOpen" class="modal-stage dataset-picker-stage">
    <section class="upload-dialog dataset-dialog member-picker advanced-member-picker" @wheel.stop>
      <button class="close" @click="addMembersOpen=false">×</button>
      <h2>{{pickerMode==='filter'?'筛选数据':'添加素材'}}</h2>
      <div class="member-picker-layout">
        <aside class="dataset-picker-filters" @wheel.stop>
          <label>搜索<input v-model="candidateQuery" placeholder="名称或备注" /></label>
          <label>素材类型<select v-model="candidateType"><option value="">全部类型</option><option value="image">图片</option><option value="video">视频</option><option value="archive">压缩文件</option><option value="other">其他</option></select></label>
          <button class="untagged-filter" :class="{active:candidateNoTags}" @click="candidateNoTags=!candidateNoTags">无标签</button>
          <div class="advanced-head"><b>高级筛选条件</b><button @click="addCandidateRule">＋ 条件</button></div>
          <div class="match-mode"><span>符合</span><button :class="{active:candidateMatch==='all'}" @click="candidateMatch='all'">全部</button><button :class="{active:candidateMatch==='any'}" @click="candidateMatch='any'">任一</button></div>
          <div class="candidate-rules"><div v-for="rule in candidateRules" :key="rule.id">
            <select v-model="rule.tag" @change="changeCandidateField(rule)"><option v-for="field in props.filterDefinitions" :key="field.key" :value="field.key">{{field.label}}</option></select>
            <select v-model="rule.operator" @change="changeCandidateOperator(rule)"><template v-if="isTime(rule.tag)"><option value="equals">等于</option><option value="lt">小于</option><option value="gt">大于</option><option value="between">位于</option></template><template v-else><option value="equals">等于</option><option value="notEquals">不等于</option><option value="contains">包含</option><option value="notContains">不包含</option></template></select>
            <div v-if="isTime(rule.tag)" class="dataset-time-range"><input v-model="rule.value" type="datetime-local" step="1" @change="rule.operator==='between' && (!rule.valueEnd || rule.valueEnd<=rule.value) ? rule.valueEnd=nextTime(rule.value) : null" /><span v-if="rule.operator==='between'">至</span><input v-if="rule.operator==='between'" v-model="rule.valueEnd" type="datetime-local" step="1" :min="nextTime(rule.value)" /></div>
            <select v-else-if="props.filterDefinitions.find(field=>field.key===rule.tag)?.values?.length" v-model="rule.value"><option value="">请选择</option><option v-for="value in props.filterDefinitions.find(field=>field.key===rule.tag)?.values" :key="value">{{value}}</option></select><input v-else v-model="rule.value" placeholder="请输入值" />
            <button class="remove-rule" @click="candidateRules=candidateRules.filter(item=>item.id!==rule.id)">×</button>
          </div></div>
        </aside>
        <div class="candidate-panel" @wheel.stop>
          <div class="candidate-selection-tools">
            <button v-if="pickerMode==='filter'||candidateSelected.length||candidateSelectionId" :disabled="pickerMode==='filter'&&!candidateSelected.length" @click="clearCandidateSelection">取消选择</button>
            <button v-if="pickerMode==='filter'" @click="selectCandidatePage">全选</button>
            <button v-else @click="candidatePageSize?selectCandidatePage():selectAllCandidates()">{{candidatePageSize?'全选当前页':'全选筛选结果'}}</button>
            <button v-if="pickerMode==='filter'" @click="invertCandidatePage">反选</button>
            <button v-else-if="candidatePageSize" @click="invertCandidatePage">反选当前页</button>
          </div>
          <div class="candidate-table-head"><span>素材名称</span><span>素材标签</span><span>关联标注</span><span>素材格式</span></div>
          <div class="candidate-list" @wheel.stop>
            <button v-for="item in filteredCandidates.slice(0,candidateRenderLimit)" :key="item.id" :disabled="pickerMode==='add'&&existingCandidateIds.includes(item.id)" :class="{selected:candidateSelectionId?!candidateExcludedIds.includes(item.id):candidateSelected.includes(item.id)}" @click="toggleCandidate(item.id)">
              <span class="candidate-name" :title="item.name"><span class="candidate-thumb"><img v-if="['图片','视频'].includes(item.type)&&item.preview_url" :src="item.preview_url" :alt="item.name" /><em v-else>{{item.type}}</em></span><b>{{item.name}}</b></span>
              <span class="candidate-tags" :title="item.tags.join('、')"><i v-for="tag in item.tags" :key="tag" :style="tagStyle(tag)">{{tag}}</i></span>
              <span class="candidate-annotation">{{item.has_annotation?'✓':''}}</span><span>{{existingCandidateIds.includes(item.id)&&pickerMode==='add'?'已在数据集':item.type}}</span>
            </button>
            <p v-if="!candidateLoading&&!filteredCandidates.length" class="dataset-empty-text">暂无符合条件的素材</p>
          </div>
          <button v-if="candidates.length>candidateRenderLimit" @click="candidateRenderLimit+=200">继续显示</button>
          <div class="candidate-footer"><span>全部 {{candidateTotal}} 项 <template v-if="pickerMode==='add'">· 已选 {{candidateSelectionId?Math.max(0,candidateTotal-candidateExcludedIds.length):candidateSelected.length}} 项</template></span><div class="candidate-page-controls"><label>每页 <select v-model="candidatePageSize" @change="candidatePage=1;clearCandidateSelection();fetchCandidatePage()"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option><option :value="0">全部</option></select> 项</label><button :disabled="candidatePage<=1||!candidatePageSize" @click="candidatePage--;fetchCandidatePage()">‹</button><button :disabled="!candidatePageSize||candidatePage*candidatePageSize>=candidateTotal" @click="candidatePage++;fetchCandidatePage()">›</button></div></div>
        </div>
      </div>
      <div class="dialog-actions"><button class="secondary" @click="addMembersOpen=false">取消</button><button v-if="pickerMode==='filter'" class="primary" :disabled="candidateLoading" @click="applyMemberFilter">应用</button><button v-else class="primary" :disabled="operationBusy||(!candidateSelected.length&&!candidateSelectionId)" @click="addMembers">添加到数据集</button></div>
    </section>
  </div>
  <div v-if="modelOpen" class="modal-stage"><section class="upload-dialog dataset-dialog"><button class="close" @click="modelOpen=false">×</button><h2>添加模型关联</h2><div class="publish-form"><label>数据集版本<select v-model="selectedVersionId"><option v-for="item in versions" :key="item.id" :value="item.id">{{item.version}}</option></select></label><label>模型<select v-model="selectedModelId" @change="selectModelCandidate"><option value="" disabled>请选择模型</option><option v-for="item in modelCandidates" :key="item.id" :value="item.id">{{item.name}}</option></select></label><label class="release-note-field">备注<textarea v-model="modelRelationRemark" rows="4" maxlength="1000" placeholder="请输入关联备注" /></label></div><div class="dialog-actions"><button class="secondary" @click="modelOpen=false">取消</button><button class="primary" :disabled="operationBusy||!selectedModelId||!selectedVersionId" @click="addModelRelation">确认关联</button></div></section></div>
  <ModelParametersDialog v-if="modelParameterTarget" :asset-id="String(modelParameterTarget.id)" :asset-name="modelParameterTarget.name" :can-edit="props.canEditModelParameters" @close="modelParameterTarget=null" @saved="loadDatasetContent" @notify="(message,kind)=>emit('notify',message,kind)" />
  <div v-if="editingModel" class="modal-stage"><section class="upload-dialog dataset-dialog" role="dialog" aria-modal="true" aria-labelledby="model-remark-title"><button class="close" aria-label="关闭编辑备注弹窗" :disabled="operationBusy" @click="editingModel=null">×</button><h2 id="model-remark-title">编辑关联备注</h2><p class="dialog-tip">{{editingModel.name}} · {{editingModel.version}}（模型和数据集版本不可修改）</p><label class="dialog-field">备注<textarea v-model="editingModelRemark" rows="4" maxlength="1000" placeholder="请输入关联备注" :disabled="operationBusy" /></label><div class="dialog-actions"><button class="secondary" :disabled="operationBusy" @click="editingModel=null">取消</button><button class="primary" :disabled="operationBusy" @click="saveModelRelationRemark">{{operationBusy?'保存中…':'保存备注'}}</button></div></section></div>
  <div v-if="versionDetail" class="modal-stage"><section class="upload-dialog dataset-dialog version-detail-dialog"><button class="close" @click="versionDetail=null">×</button><h2>{{versionDetail.version}} 版本详情</h2><div class="version-detail-summary"><span>数据数量 {{versionDetail.member_count}} 项</span><span>总容量 {{formatBytes(versionDetail.total_size)}}</span><span>创建人 {{versionDetail.created_by_name||versionDetail.created_by}}</span><span>发布时间 {{formatDate(versionDetail.created_at)}}</span></div><p>{{versionDetail.release_note||'暂无发布说明'}}</p><div class="version-member-list"><article v-for="item in versionDetail.members" :key="item.asset_id"><b :title="item.snapshot.name">{{item.snapshot.name}}</b><span>{{typeLabels[item.snapshot.type]||item.snapshot.type}} · {{formatBytes(item.snapshot.size)}}</span><small :title="item.snapshot.sha256">校验值 {{item.snapshot.sha256||'—'}}</small><span>{{Object.values(item.snapshot.tags||{}).flat().join(' · ')}}</span><span>{{item.snapshot.remark}}</span></article></div><button v-if="versionDetail.members.length<(versionDetail.member_total||versionDetail.member_count)" :disabled="versionDetailLoading" @click="loadMoreVersionMembers">{{versionDetailLoading?'正在加载…':'继续显示'}}</button></section></div>
  <div v-if="confirmOpen" class="modal-stage confirm-stage"><section class="upload-dialog confirm-dialog"><h2>操作确认</h2><p>{{confirmText}}</p><div class="dialog-actions"><button class="secondary" @click="confirmOpen=false">取消</button><button class="primary" :disabled="operationBusy" @click="runConfirm">{{operationBusy?'处理中':'确认'}}</button></div></section></div>
</template>

<style scoped>
.dataset-filters{display:grid;grid-template-columns:minmax(220px,1fr) 130px 140px 165px auto;gap:10px;align-items:center;margin-bottom:16px;padding:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px}.dataset-filters input,.dataset-filters select,.dataset-filters button,.demo-switch select{min-width:0;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);padding:9px 10px}.demo-switch{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px;white-space:nowrap}.dataset-table-wrap,.dataset-members-panel,.dataset-version-list,.dataset-models{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}.dataset-version-list{overflow:auto}.dataset-table{overflow:auto}.dataset-row{min-width:1180px;display:grid;grid-template-columns:minmax(160px,1.25fr) 55px 75px minmax(220px,1.2fr) 70px 72px 132px 132px 65px 120px;gap:8px;align-items:center;padding:13px 16px;border-top:1px solid var(--line);font-size:12px;color:var(--ink)}.dataset-row.head{border-top:0;background:color-mix(in srgb,var(--panel) 94%,var(--ink));color:var(--muted);font-weight:700}.dataset-name{display:grid!important;gap:3px!important;min-width:0!important;padding:0!important;border:0!important;background:transparent!important;text-align:left!important}.dataset-name b,.dataset-name small,.dataset-counts{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.dataset-name b{color:var(--ink)}.dataset-name small{color:var(--muted)}.dataset-status{display:inline-flex;width:max-content;padding:4px 8px;border-radius:99px;background:var(--accent-soft);color:var(--accent);font-style:normal;font-size:11px;font-weight:700}.dataset-date{white-space:nowrap}.dataset-status.editing{background:#fff3d9;color:#a86605}.dataset-status.published{background:#e6f5ee;color:#20825b}.dataset-actions{display:flex;gap:2px}.dataset-actions button,.version-row button,.link-button{border:0;background:transparent;color:var(--accent);padding:3px;font-size:11px}.dataset-detail-head{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:end}.back-button{grid-column:1/3;justify-self:start;padding:0!important;border:0!important;background:transparent!important;color:var(--muted)!important}.dataset-title{display:flex;align-items:center;gap:12px;min-width:0}.dataset-title h1{margin:0;color:var(--ink);font-size:30px}.dataset-title p{margin:5px 0 0;color:var(--muted)}.dataset-detail-actions{display:flex;gap:8px}.dataset-summary{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;margin:18px 0;background:var(--line);border:1px solid var(--line);border-radius:9px;overflow:hidden}.dataset-summary>div{display:grid;gap:5px;padding:15px;background:var(--panel)}.dataset-summary small{color:var(--muted)}.dataset-summary b{color:var(--ink)}.dataset-tabs{display:flex;gap:4px;margin-bottom:14px;border-bottom:1px solid var(--line)}.dataset-tabs button{border:0;background:transparent;color:var(--muted);padding:11px 16px;border-bottom:2px solid transparent}.dataset-tabs button.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:700}.dataset-overview{display:grid;grid-template-columns:1fr 1fr;gap:14px}.dataset-overview article{padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:10px}.dataset-overview h2{margin:0 0 16px;color:var(--ink);font-size:17px}.type-bars{display:grid;gap:13px}.type-bars>div{display:grid;grid-template-columns:62px 1fr 70px;gap:10px;align-items:center;color:var(--muted);font-size:12px}.type-bars i{height:8px;border-radius:8px;background:color-mix(in srgb,var(--panel) 84%,var(--ink));overflow:hidden}.type-bars em{display:block;height:100%;border-radius:8px}.type-bars b{text-align:right;color:var(--ink)}.tag-cloud{display:flex;flex-wrap:wrap;gap:9px}.tag-cloud span{padding:8px 10px;border:1px solid var(--line);border-radius:7px;color:var(--muted)}.tag-cloud b{margin-left:8px;color:var(--ink)}.dataset-empty-text{margin:0;color:var(--muted);font-size:12px}.dataset-activity ul{list-style:none;padding:0;margin:0;display:grid;gap:12px}.dataset-activity li{display:grid;grid-template-columns:80px 1fr auto;gap:10px}.dataset-activity li span,.dataset-activity li small{color:var(--muted)}.overview-model{display:grid;grid-template-columns:1fr auto;gap:5px;padding:10px 0;border-bottom:1px solid var(--line)}.overview-model b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.overview-model span{color:var(--muted)}.member-toolbar{display:flex;justify-content:space-between;padding:13px 15px;border-bottom:1px solid var(--line)}.member-toolbar>div{display:flex;gap:7px}.member-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;padding:14px}.member-grid article{position:relative;display:grid;grid-template-columns:72px minmax(0,1fr);gap:11px;padding:10px;border:1px solid var(--line);border-radius:8px}.member-grid article.selected{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft)}.member-preview{display:grid;place-items:center;min-height:72px;border-radius:6px;background:linear-gradient(135deg,#334b65,#698ba0);color:white;font-size:11px}.member-select{position:absolute;top:5px;right:5px;width:22px;height:22px;padding:0;border:1px solid #ffffff99;border-radius:5px;background:#13253caa;color:white}.member-grid article>div:last-child{min-width:0}.member-grid article>div>b,.member-grid p{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.member-grid p{margin:4px 0;color:var(--muted);font-size:12px}.member-grid article span{display:flex;gap:4px;overflow:hidden}.member-grid article i{padding:2px 5px;border-radius:4px;background:var(--accent-soft);color:var(--accent);font-size:10px;font-style:normal;white-space:nowrap}.member-grid small{display:block;margin-top:6px;color:var(--muted)}.version-row{min-width:1000px;display:grid;grid-template-columns:65px minmax(180px,1fr) 90px 80px 80px 150px 75px 190px;gap:12px;align-items:center;padding:13px 16px;border-top:1px solid var(--line);font-size:12px}.version-row.head{border:0;background:color-mix(in srgb,var(--panel) 94%,var(--ink));color:var(--muted);font-weight:700}.version-row>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.version-row>span:last-child{display:flex;gap:7px;overflow:visible}.dataset-models{padding:14px}.dataset-models article{display:grid;grid-template-columns:62px 1fr auto auto;gap:14px;align-items:center;padding:13px;border-bottom:1px solid var(--line)}.model-icon{display:grid;place-items:center;width:58px;height:48px;border-radius:7px;background:#243c50;color:white;font-size:10px}.dataset-models article>div:nth-child(2){display:grid;gap:3px}.dataset-models span,.dataset-models small{color:var(--muted)}.dataset-models i{font-style:normal;color:var(--accent)}.dataset-dialog{width:min(620px,100%)}.compare-dialog{width:min(760px,100%);max-height:88vh;overflow:auto}.dialog-field{display:grid;gap:8px;color:var(--muted);font-size:12px}.dialog-field textarea{resize:vertical}.publish-summary{display:grid;grid-template-columns:1fr auto;gap:10px;margin:18px 0;padding:13px;background:var(--accent-soft);border-radius:7px}.dialog-tip{color:var(--muted);font-size:12px}.compare-selectors{display:grid;grid-template-columns:1fr auto 1fr;align-items:end;gap:10px}.compare-selectors label{display:grid;gap:7px;color:var(--muted);font-size:12px}.compare-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:18px 0}.compare-stats button{display:grid;gap:3px;padding:12px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink)}.compare-stats span{color:var(--muted);font-size:11px}.compare-stats .added{border-color:color-mix(in srgb,#16a34a 42%,var(--line));background:color-mix(in srgb,#16a34a 10%,var(--panel));color:#16a34a}.compare-stats .removed{border-color:color-mix(in srgb,#dc4c4c 42%,var(--line));background:color-mix(in srgb,#dc4c4c 10%,var(--panel));color:#dc4c4c}.compare-stats .unchanged{border-color:color-mix(in srgb,#64748b 36%,var(--line));background:color-mix(in srgb,#64748b 9%,var(--panel));color:#64748b}.compare-stats .changed{border-color:color-mix(in srgb,#7c3aed 42%,var(--line));background:color-mix(in srgb,#7c3aed 10%,var(--panel));color:#7c3aed}.compare-groups{display:grid;gap:8px}.compare-groups>section{border:1px solid var(--line);border-radius:7px;overflow:hidden}.compare-groups>section>button{width:100%;display:flex;align-items:center;justify-content:space-between;padding:11px 12px;border:0;background:var(--panel);color:var(--ink);text-align:left}.compare-groups>section>button span{display:grid;gap:3px}.compare-groups>section>button small{color:var(--muted)}.compare-groups>section>button i{font-style:normal;color:var(--accent)}.compare-group-items{border-top:1px solid var(--line);background:color-mix(in srgb,var(--panel) 96%,var(--ink))}.compare-group-items>div{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;padding:9px 12px;border-top:1px solid var(--line)}.compare-group-items>div:first-child{border-top:0}.compare-group-items em{width:max-content;padding:2px 6px;border-radius:4px;background:var(--accent-soft);color:var(--accent);font-size:10px;font-style:normal}.compare-group-items b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.compare-preview{border:1px solid var(--line);border-radius:7px}.compare-preview>div{display:flex;justify-content:space-between;padding:10px;border-top:1px solid var(--line)}.compare-preview>div:first-child{border:0}.compare-preview span{color:var(--muted)}.candidate-filters{display:grid;grid-template-columns:1fr 140px;gap:9px;margin:16px 0}.candidate-list{display:grid;gap:7px;max-height:330px;overflow:auto}.candidate-list button{display:grid;grid-template-columns:24px 1fr 70px 1fr;gap:8px;align-items:center;text-align:left}.candidate-list button.selected{border-color:var(--accent);background:var(--accent-soft)}.candidate-list i{font-style:normal;color:var(--accent)}.candidate-list b,.candidate-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.candidate-list small{color:var(--muted)}.confirm-stage{z-index:400}.skin-command .dataset-status.editing{background:#3b301a;color:#f4bf5f}.skin-command .dataset-status.published{background:#173d35;color:#55d6a5}
.member-toolbar button{min-width:76px;height:36px;border-radius:7px;font-weight:650}.member-toolbar .danger-action{border:1px solid color-mix(in srgb,#dc4c4c 45%,var(--line));background:color-mix(in srgb,#dc4c4c 10%,var(--panel));color:#dc4c4c}.member-preview{position:relative;overflow:hidden}.member-preview img{width:100%;height:100%;min-height:72px;object-fit:cover}.member-preview>i{position:absolute;inset:0;display:grid;place-items:center;color:white;font-size:20px;text-shadow:0 1px 4px #000}.model-toolbar{display:flex;justify-content:flex-end;padding:0 0 12px}.publish-form{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:18px 0}.publish-form label{display:grid;gap:7px;color:var(--muted);font-size:12px}.publish-form input,.publish-form select,.publish-form textarea{width:100%;box-sizing:border-box;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);padding:10px 11px}.release-note-field{grid-column:1/3}.release-note-field textarea{min-height:128px;resize:vertical;line-height:1.6}.advanced-member-picker{width:min(1080px,96vw)}.member-picker-layout{display:grid;grid-template-columns:300px minmax(0,1fr);gap:14px;margin:16px 0}.dataset-picker-filters{display:grid;align-content:start;gap:9px;padding:13px;border:1px solid var(--line);border-radius:8px;background:color-mix(in srgb,var(--panel) 96%,var(--ink))}.dataset-picker-filters>label{display:grid;gap:5px;color:var(--muted);font-size:12px}.dataset-picker-filters input,.dataset-picker-filters select{width:100%;min-width:0;box-sizing:border-box;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);padding:8px}.candidate-rules{display:grid;gap:8px}.candidate-rules>div{position:relative;display:grid;grid-template-columns:1fr 88px;gap:5px;padding:8px 26px 8px 8px;border:1px solid var(--line);border-radius:7px}.candidate-rules>div>select:nth-of-type(3),.candidate-rules>div>input{grid-column:1/3}.candidate-rules .remove-rule{position:absolute;right:2px;top:2px;border:0}.apply-candidate-filter{width:100%}.advanced-member-picker .candidate-list{max-height:520px}.advanced-member-picker .candidate-list button{grid-template-columns:24px 64px minmax(0,1fr) minmax(0,.7fr)}.candidate-thumb{display:grid;place-items:center;width:60px;height:48px;overflow:hidden;border-radius:5px;background:color-mix(in srgb,var(--panel) 85%,var(--ink))}.candidate-thumb img{width:100%;height:100%;object-fit:cover}.candidate-thumb em{font-size:10px;font-style:normal;color:var(--muted)}@media(max-width:1100px){.dataset-filters{grid-template-columns:1fr 1fr 1fr}.dataset-summary{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.dataset-filters{grid-template-columns:1fr 1fr}.dataset-detail-head{display:block}.back-button{margin-bottom:12px}.dataset-title{align-items:flex-start}.dataset-title h1{font-size:25px}.dataset-detail-actions{display:grid;grid-template-columns:1fr 1fr;margin-top:14px}.dataset-summary{grid-template-columns:1fr 1fr}.dataset-tabs{overflow:auto}.dataset-tabs button{white-space:nowrap}.dataset-overview{grid-template-columns:1fr}.member-toolbar{align-items:stretch;flex-direction:column;gap:8px}.member-toolbar>div{display:grid;grid-template-columns:repeat(3,1fr)}.dataset-models article{grid-template-columns:52px minmax(0,1fr)}.dataset-models article>i,.dataset-models article>button{grid-column:2}.compare-stats{grid-template-columns:1fr 1fr}.candidate-filters{grid-template-columns:1fr}.candidate-list button{grid-template-columns:24px 1fr 60px}.candidate-list small{grid-column:2/4}}
.overview-title{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.overview-title h2{margin:0}.overview-title .link-button{font-size:12px}.dataset-models .danger-inline{border:1px solid color-mix(in srgb,#dc4c4c 42%,var(--line));border-radius:6px;background:color-mix(in srgb,#dc4c4c 9%,var(--panel));color:#dc4c4c;padding:7px 10px}.dataset-models article>div:nth-child(2)>span{max-width:520px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.dataset-time-range{grid-column:1/3;display:grid;gap:6px;min-width:0}.dataset-time-range span{text-align:center;color:var(--muted)}.dataset-time-range input{color-scheme:light}.skin-command .dataset-time-range input{color-scheme:dark}.member-picker-layout{max-height:70vh;overflow:auto}@media(max-width:760px){.member-picker-layout{grid-template-columns:1fr}} .copy-dialog{width:min(500px,calc(100vw - 32px));box-sizing:border-box;padding:26px;border:1px solid var(--line);border-radius:14px;background:var(--panel);color:var(--ink);box-shadow:0 20px 60px #0003}.copy-dialog h2{margin:0 36px 24px 0;font-size:22px;font-weight:700}.copy-form{display:grid;gap:20px}.copy-form label{display:grid;gap:9px;font-size:14px;font-weight:600;color:var(--ink)}.copy-form input,.copy-form select{box-sizing:border-box;width:100%;height:42px;padding:0 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font:inherit;font-weight:400;outline:none;color-scheme:light}.copy-form input:focus,.copy-form select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}.copy-dialog .dialog-actions{display:flex;justify-content:flex-end;gap:12px;margin-top:26px;padding-top:20px;border-top:1px solid var(--line)}.copy-dialog .dialog-actions button{height:38px;min-width:88px;padding:0 18px;border-radius:8px;font-size:14px;font-weight:600}.skin-command .copy-form input,.skin-command .copy-form select{color-scheme:dark}.copy-dialog button:disabled{opacity:.55;cursor:not-allowed}.candidate-selection-tools{display:flex;gap:8px;margin-bottom:10px}.candidate-selected-chips{display:flex;flex-wrap:wrap;gap:6px;max-height:110px;overflow:auto;margin-bottom:10px}.candidate-selected-chips button{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.version-detail-dialog{width:min(800px,95vw);max-height:85vh;overflow:auto}.version-detail-summary{display:flex;flex-wrap:wrap;gap:12px;color:var(--muted)}.version-member-list article{display:grid;gap:6px;padding:12px;border-bottom:1px solid var(--line)}.version-member-list b,.version-member-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.version-member-list small{color:var(--muted)}.candidate-selection-tools button,.candidate-selected-chips button{height:34px;padding:0 12px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);font-size:13px;font-weight:600}.dataset-picker-filters .untagged-filter{display:flex;align-items:center;justify-content:flex-start;width:100%;height:36px;min-height:36px;padding:0 12px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink);white-space:nowrap;writing-mode:horizontal-tb}.dataset-picker-filters .untagged-filter.active{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}.advanced-member-picker .candidate-list>button{padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink)}.advanced-member-picker .candidate-list>button.selected{border-color:var(--accent);background:var(--accent-soft)}.advanced-member-picker .candidate-list{scrollbar-width:thin;scrollbar-color:var(--line) transparent}.advanced-member-picker .pagination select{height:32px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}.advanced-member-picker .pagination button{display:grid;place-items:center;width:32px;height:32px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}.advanced-member-picker .pagination button:disabled{opacity:.4}.candidate-selected-chips button{max-width:220px}
.model-relation-actions{display:flex;align-items:center;gap:8px}.model-relation-actions button{white-space:nowrap}@media(max-width:760px){.dataset-models article>.model-relation-actions{grid-column:2;flex-wrap:wrap}}
.dataset-models article{grid-template-columns:62px minmax(0,1fr) auto}.dataset-models .model-summary{min-width:0}.dataset-models .model-summary>.model-version{color:var(--muted);font-size:12px}.model-configured-parameters{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.model-configured-parameters span{max-width:100%;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--accent-soft);color:var(--ink);font-size:12px;overflow-wrap:anywhere}.model-configured-parameters b{font-weight:700}@media(max-width:760px){.dataset-models article{grid-template-columns:52px minmax(0,1fr)}.dataset-models article>.model-relation-actions{grid-column:2}}
.advanced-member-picker{width:min(1560px,96vw);height:min(860px,92vh);max-height:92vh;box-sizing:border-box;display:flex;flex-direction:column;overflow:hidden}
.advanced-member-picker .member-picker-layout{display:grid;grid-template-columns:270px minmax(0,1fr);flex:1;min-height:0;max-height:none;overflow:hidden}
.advanced-member-picker .dataset-picker-filters{min-height:0;overflow-y:auto;overscroll-behavior:contain}
.advanced-member-picker .candidate-panel{display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden}
.advanced-member-picker .candidate-list{flex:1;min-height:0;max-height:none;overflow-y:auto;overscroll-behavior:contain;align-content:start;grid-auto-rows:max-content}
.advanced-member-picker .candidate-table-head,.advanced-member-picker .candidate-list>button{display:grid;grid-template-columns:minmax(330px,1.7fr) minmax(120px,.8fr) 76px 100px;align-items:center;gap:12px}
.advanced-member-picker .candidate-table-head{padding:10px 12px;border-bottom:1px solid var(--line);color:var(--muted);font-size:12px;font-weight:700}
.advanced-member-picker .candidate-list>button{width:100%;min-height:60px;text-align:left}
.advanced-member-picker .candidate-list>button:disabled{opacity:.55;cursor:not-allowed}
.advanced-member-picker .candidate-name{display:flex;align-items:center;min-width:0;gap:10px}
.advanced-member-picker .candidate-name b{white-space:normal;overflow-wrap:anywhere;line-height:1.35}
.advanced-member-picker .candidate-tags{display:flex;flex-wrap:wrap;gap:4px;min-width:0}
.advanced-member-picker .candidate-tags i{padding:3px 5px;border:1px solid;border-radius:4px;font-size:11px;font-style:normal}
.advanced-member-picker .candidate-annotation{text-align:center;color:var(--accent);font-size:18px;font-weight:700}
.advanced-member-picker .candidate-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;color:var(--muted);font-size:12px}
.advanced-member-picker .candidate-page-controls{display:flex;align-items:center;gap:7px}
.advanced-member-picker .candidate-page-controls button{display:grid;place-items:center;width:32px;height:32px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
.advanced-member-picker .candidate-page-controls select{height:32px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
.advanced-member-picker .dialog-actions{flex:none}
.dataset-project-field{display:grid;gap:8px;color:var(--muted);font-size:12px}
.dataset-project-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.dataset-project-heading i{color:#dc4c4c;font-style:normal}
.dataset-project-heading button{border:0;background:transparent;color:var(--accent);font:inherit;font-weight:700;cursor:pointer}
.dataset-project-heading button:disabled{opacity:.45;cursor:not-allowed}
.dataset-project-options{display:flex;flex-wrap:wrap;gap:8px;max-height:128px;overflow:auto;padding:10px;border:1px solid var(--line);border-radius:7px}
.dataset-project-options label{display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border:1px solid var(--line);border-radius:6px;color:var(--ink);cursor:pointer}
.dataset-project-options input{width:auto!important;margin:0;accent-color:var(--accent)}
.dataset-project-hint{margin:0;color:#b45309;font-size:12px}
.dataset-pagination{display:flex;align-items:center;justify-content:space-between;gap:12px}
.dataset-pagination>span:first-child{margin-right:0}
.dataset-pagination .page-controls{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-left:auto;white-space:nowrap}
.dataset-pagination .page-controls label{display:flex;align-items:center;gap:4px;white-space:nowrap}
.dataset-pagination .page-controls>span{color:var(--muted);font-size:12px;min-width:18px;text-align:center}
.version-toolbar{display:flex;justify-content:flex-end;padding:14px 16px;border-bottom:1px solid var(--line)}
.version-toolbar button{min-height:36px;border-radius:7px;font-weight:650}
.member-grid .annotation-badge{color:var(--accent);font-style:normal;font-weight:600}
@media(max-width:900px){.advanced-member-picker .member-picker-layout{grid-template-columns:220px minmax(0,1fr)}.advanced-member-picker .candidate-table-head,.advanced-member-picker .candidate-list>button{grid-template-columns:minmax(200px,1fr) minmax(90px,.5fr) 60px 80px;gap:6px}}
@media(max-width:700px){.advanced-member-picker .member-picker-layout{grid-template-columns:1fr;overflow-y:auto}.advanced-member-picker .dataset-picker-filters{max-height:230px}.advanced-member-picker .candidate-panel{min-height:300px}}
</style>




