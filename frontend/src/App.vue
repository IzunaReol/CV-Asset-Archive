<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from './api'

type Page = 'library' | 'relations' | 'lineage' | 'downloads' | 'trash' | 'tags' | 'formats' | 'admin'
type Skin = 'light' | 'command'
type TagKey = string
type FilterOperator = 'equals' | 'notEquals' | 'contains' | 'notContains' | 'lt' | 'gt' | 'between'
type FilterRule = { id: number; tag: TagKey; operator: FilterOperator; value: string; valueEnd?: string }
type AssetId = string | number
type Asset = { id:AssetId; name:string; type:string; status:string; scene:string; algorithm:string; tone:string; mark:string; remark:string; createdAt:string; updatedAt:string; preview_url?:string|null; tags:Partial<Record<TagKey,string|string[]>> }

const page = ref<Page>('library')
const skin = ref<Skin>((localStorage.getItem('cv-archive-skin') as Skin) || 'light')
const selected = ref<AssetId[]>([])
const query = ref('')
const status = ref('全部状态')
const scene = ref('全部场景')
const noTags = ref(false)
const selectedAssetTypes = ref<string[]>([])
const assetPage = ref(1)
const assetPageSize = ref(50)
const assetSort = ref('created_at')
const assetDirection = ref<'asc'|'desc'>('desc')
const matchMode = ref<'all' | 'any'>('all')
const filterRules = ref<FilterRule[]>([{ id: 1, tag: 'status', operator: 'equals', value: '' }])
const appliedMatchMode = ref<'all' | 'any'>('all')
const appliedFilterRules = ref<FilterRule[]>([])
let nextRuleId = 2
const density = ref<'comfortable' | 'compact'>('comfortable')
const detailId = ref<AssetId | null>(null)
const detailAsset = ref<any>(null)
const annotationSources = ref<any[]>([])
const selectedAnnotationSourceId = ref('')
const annotationLoading = ref(false)
const mediaViewerOpen = ref(false)
const pickerPreviewAsset = ref<any>(null)
const mediaViewerZoom = ref(1)
const mediaViewerAnnotations = ref(true)
const detailSheetScrolling = ref(false)
let detailScrollTimer: number | null = null
const toast = ref('')
const toastKind = ref<'success'|'error'>('success')
const confirmOpen = ref(false)
const confirmMessage = ref('')
const confirmBusy = ref(false)
let pendingConfirmAction: (() => void | Promise<void>) | null = null
const showLogin = ref(!api.session())
const loginUsername = ref('admin')
const loginPassword = ref('admin')
const loginBusy = ref(false)
const loginError = ref('')
const currentUser = ref<any>(api.session()?.user || null)
const uploadOpen = ref(false)
const uploadFiles = ref<File[]>([])
const uploadTypeOverrides = ref<Record<string,string>>({})
const uploadBusy = ref(false)
const uploadProgress = ref(0)
const uploadError = ref('')
const batchTagOpen = ref(false)
const batchTagAction = ref<'add'|'remove'>('add')
const batchTagKey = ref<TagKey>('status')
const batchTagValue = ref('')
const batchTagTarget = ref<'library'|'upload'>('library')
const uploadTags = ref<Record<string,string[]>>({})
const remarkDraft = ref('')
const remarkSaving = ref(false)
const revokeReason = ref('')
const relationTargetId = ref('')
const relationTargetName = ref('')
const relationType = ref('contains')
const relationWorkflow = ref<'auto'|'model'|'manual'>('auto')
const relationSourceAssets = ref<any[]>([])
const relationPickerOpen = ref(false)
const relationPickerMode = ref<'source'|'target'>('source')
const relationPickerItems = ref<any[]>([])
const relationPickerQuery = ref('')
const relationPickerType = ref('')
const relationPickerPage = ref(1)
const relationPickerTotal = ref(0)
const relationPickerLoading = ref(false)
const relationPickerPageSize = ref(50)
const relationPickerNoTags = ref(false)
const relationPickerMatch = ref<'all'|'any'>('all')
const relationPickerRules = ref<FilterRule[]>([])
const relationPickerSelection = ref<any[]>([])
const relationPickerContext = ref<'source'|'target'|'auto-image'|'auto-annotation'|'model'|'model-target'>('source')
const relationPickerOriginPage = ref<Page>('relations')
const autoImages = ref<any[]>([])
const autoAnnotations = ref<any[]>([])
const selectedModel = ref<any>(null)
const modelTargets = ref<any[]>([])
const relationPreviewOpen = ref(false)
const relationPreviewKind = ref<'auto'|'general'>('general')
const relationPreview = ref<any>(null)
const relationSubmitting = ref(false)
const lineagePickerOpen = ref(false)
const lineagePickerItems = ref<any[]>([])
const lineagePickerQuery = ref('')
const lineagePickerPage = ref(1)
const lineagePickerTotal = ref(0)
const lineagePickerLoading = ref(false)
const jobRows = ref<any[]>([])
const jobTotal = ref(0)
let jobPoll: number | null = null
const tagRows = ref<any[]>([])
const demoState = ref<'normal' | 'loading' | 'empty' | 'error' | 'forbidden'>('normal')
const relationPage = ref(1)
const relationPageSize = ref(10)
const relationDetailId = ref<string | number | null>(null)
const relationDetailData = ref<any>(null)
const relationTotal = ref(0)
const relationHistoryQuery = ref('')
const relationHistoryType = ref('')
const relationHistoryStatus = ref('')
const relationHistoryCreator = ref('')
const relationHistoryFrom = ref('')
const relationHistoryTo = ref('')
const assetTotal = ref(0)
const assetFilteredTotal = ref(0)
const untaggedTotal = ref(0)
const assetTypeCounts = ref<Record<string,number>>({image:0,video:0,annotation:0,model:0,archive:0,image_annotation:0,other:0})
const storageStats = ref({total:0,used:0,free:0})
const savedViewRows = ref<any[]>([])
const collectionOpen = ref(false)
const collectionName = ref('')
const collectionDescription = ref('')
const collectionFreeze = ref(true)
const tagOpen = ref(false)
const editingTagKey = ref<string | null>(null)
const newTag = ref({name:'',key:'',values:'',color:'#64748b',free_input:false})
const tagPickerColor = ref('#64748b')
const tagValueRows = ref<Array<{id:number;value:string;editing:boolean}>>([])
let nextTagValueId = 1
const savedViewOpen = ref(false)
const savedViewName = ref('')
const editingViewId = ref<string | null>(null)
const userRows = ref<any[]>([])
const auditRows = ref<any[]>([])
const userOpen = ref(false)
const editingUserId = ref<string|null>(null)
const newUser = ref({username:'',password:'',role:'viewer',status:'active'})
const formatRows = ref<any[]>([])
const formatOpen = ref(false)
const editingFormatType = ref('')
const newFormatType = ref('')
const formatRemark = ref('')
const formatValueRows = ref<Array<{id:number;value:string;editing:boolean;protected:boolean}>>([])
let nextFormatValueId = 1
const trashAssets = ref<Asset[]>([])
const trashSelected = ref<AssetId[]>([])
const trashPage = ref(1)
const trashPageSize = ref(50)
const trashTotal = ref(0)

const assets = ref<Asset[]>([])
const tagDefinitions = computed(() => tagRows.value.map((tag:any) => ({key:tag.key,label:tag.name,values:tag.values || [],free_input:Boolean(tag.free_input)})))
const filterDefinitions = computed(() => [{key:'remark',label:'备注',values:[],free_input:true},{key:'created_at',label:'创建时间',values:[],free_input:false,time:true},{key:'updated_at',label:'修改时间',values:[],free_input:false,time:true}, ...tagDefinitions.value])
const uploadTagEntries = computed(() => Object.entries(uploadTags.value).flatMap(([key,values]) => values.map(value => ({key,value,label:tagDefinitions.value.find((tag:any)=>tag.key===key)?.label || key}))))
const assetTypeLabels: Record<string,string> = { image:'图片', video:'视频', annotation:'标注', model:'模型', snapshot:'数据集', manual:'数据集', archive:'压缩文件', image_annotation:'图片+标注', other:'其他' }
const manageableFormatTypes = ['image','video','annotation','model','archive','image_annotation']
const availableFormatTypes = computed(() => manageableFormatTypes.filter(type => !formatRows.value.some(row => row.asset_type === type)))
const relationTypeLabels: Record<string,string> = { annotates:'对应标注', contains:'属于数据集', trained_on:'用于训练', produced_by:'由训练产生', version_of:'版本关系' }
const jobTypeLabels: Record<string,string> = { export:'素材导出' }
const jobStateLabels: Record<string,string> = { queued:'等待处理', running:'处理中', succeeded:'已完成', failed:'失败' }
const roleLabels: Record<string,string> = { admin:'管理员', data_manager:'数据管理员', annotator:'标注员', ml_engineer:'算法工程师', viewer:'只读访客' }
const userStatusLabels: Record<string,string> = { active:'正常', disabled:'已停用' }
const auditActionLabels: Record<string,string> = { 'asset.created':'创建素材', 'asset.deleted':'删除素材', 'asset.batch_deleted':'移入回收站', 'asset.batch_restored':'还原素材', 'asset.remark_updated':'修改素材备注', 'trash.emptied':'清空回收站', 'asset.tags_updated':'修改素材标签', 'export.created':'创建导出任务', 'relation.created':'建立关联关系', 'relation.revoked':'撤销关联关系' }

const relationHistory = ref<any[]>([])
const lineageRoot = ref<any>(null)
const lineageNodes = ref<any[]>([])
const lineageEdges = ref<any[]>([])
const lineageLoading = ref(false)
const lineageView = ref<'graph'|'list'>('graph')
const lineageTypeFilter = ref('')
const lineageRelationFilter = ref('')
const effectiveAssetPageSize = computed(() => assetPageSize.value === 0 ? 200 : assetPageSize.value)
const assetPages = computed(() => assetPageSize.value === 0 ? 1 : Math.max(1, Math.ceil(assetFilteredTotal.value / assetPageSize.value)))
watch(skin, (value) => localStorage.setItem('cv-archive-skin', value))

const filtered = computed(() => assets.value)

const activeAsset = computed(() => detailAsset.value || assets.value.find((asset) => asset.id === detailId.value))
const viewerAsset = computed(() => pickerPreviewAsset.value || activeAsset.value)
const mediaPageAssets = computed(() => filtered.value.filter(asset => asset.type === '图片' || asset.type === '视频'))
const activeMediaIndex = computed(() => mediaPageAssets.value.findIndex(asset => String(asset.id) === String(detailId.value)))
const hasPreviousMedia = computed(() => activeMediaIndex.value > 0)
const hasNextMedia = computed(() => activeMediaIndex.value >= 0 && activeMediaIndex.value < mediaPageAssets.value.length - 1)
const pagedRelations = computed(() => relationHistory.value)
const relationPages = computed(() => Math.max(1, Math.ceil(relationTotal.value / relationPageSize.value)))
const activeRelation = computed(() => relationDetailData.value || relationHistory.value.find((item) => item.id === relationDetailId.value) || lineageEdges.value.find((item:any) => item.id === relationDetailId.value))
const allCurrentSelected = computed(() => Boolean(filtered.value.length) && filtered.value.every(asset => selected.value.includes(asset.id)))
const relationSourceIds = computed(() => relationSourceAssets.value.map(item => String(item.id)))
const relationPickerSelectedIds = computed(() => relationPickerSelection.value.map(item => String(item.id)))
const relationPickerPages = computed(() => relationPickerPageSize.value === 0 ? 1 : Math.max(1,Math.ceil(relationPickerTotal.value/relationPickerPageSize.value)))
const filteredLineageEdges = computed(() => lineageEdges.value.filter((edge:any) => (!lineageRelationFilter.value || edge.relation_type===lineageRelationFilter.value) && (!lineageTypeFilter.value || edge.source_type===lineageTypeFilter.value || edge.target_type===lineageTypeFilter.value)))
const lineageGroups = computed(() => Object.entries(filteredLineageEdges.value.reduce((groups:Record<string,any[]>,edge:any) => { const key=String(edge.source_id)===String(lineageRoot.value?.id) ? edge.target_type : edge.source_type; (groups[key || 'asset'] ||= []).push(edge); return groups },{})))
const effectiveTrashPageSize = computed(() => trashPageSize.value === 0 ? 200 : trashPageSize.value)
const trashPages = computed(() => trashPageSize.value === 0 ? 1 : Math.max(1, Math.ceil(trashTotal.value / trashPageSize.value)))
const allTrashSelected = computed(() => Boolean(trashAssets.value.length) && trashAssets.value.every(asset => trashSelected.value.includes(asset.id)))
const storageUsedPercent = computed(() => storageStats.value.total ? Math.round(storageStats.value.used / storageStats.value.total * 100) : 0)
const storageFreePercent = computed(() => storageStats.value.total ? 100 - storageUsedPercent.value : 0)
const confirmTitle = computed(() => confirmMessage.value.includes('还原') ? '还原确认' : '删除确认')
const confirmActionText = computed(() => confirmMessage.value.includes('还原') ? '确认还原' : confirmMessage.value.includes('清空回收站') ? '确认清空' : '确认删除')

function toggleSelect(id: AssetId) {
  selected.value = selected.value.includes(id) ? selected.value.filter((item) => item !== id) : [...selected.value, id]
}

function selectCurrentPage() {
  selected.value = Array.from(new Set([...selected.value, ...filtered.value.map(asset => asset.id)]))
}

function assetListParams(page:number, pageSize:number) {
  const params = new URLSearchParams({page:String(page),page_size:String(pageSize),match:appliedMatchMode.value,sort:assetSort.value,direction:assetDirection.value})
  if (query.value.trim()) params.set('q', query.value.trim())
  if (noTags.value) params.set('no_tags','true')
  selectedAssetTypes.value.forEach(type => params.append('asset_type', type))
  appliedFilterRules.value.forEach(rule => params.append('tag', `${rule.tag}:${rule.operator}:${serializedFilterValue(rule)}`))
  return params
}

async function loadAllAssetPages() {
  const first = await api.assets(assetListParams(1, 200))
  const items = [...first.items]
  const pageCount = Math.ceil(first.total / 200)
  for (let pageNumber = 2; pageNumber <= pageCount; pageNumber += 1) {
    const result = await api.assets(assetListParams(pageNumber, 200))
    items.push(...result.items)
  }
  return {items,total:first.total}
}

function invertCurrentPageSelection() {
  const currentIds = filtered.value.map(asset => asset.id)
  const currentSet = new Set(currentIds)
  selected.value = [...selected.value.filter(id => !currentSet.has(id)), ...currentIds.filter(id => !selected.value.includes(id))]
}

function askConfirmation(message:string, action:() => void | Promise<void>) {
  confirmMessage.value = message
  pendingConfirmAction = action
  confirmOpen.value = true
}

async function runConfirmedAction() {
  if (!pendingConfirmAction) return
  confirmBusy.value = true
  try {
    await pendingConfirmAction()
    confirmOpen.value = false
    pendingConfirmAction = null
  } catch (error) {
    notifyError(error instanceof Error ? error.message : '删除失败')
  } finally { confirmBusy.value = false }
}

function cancelConfirmation() {
  if (confirmBusy.value) return
  confirmOpen.value = false
  pendingConfirmAction = null
}

function notify(message: string, kind: 'success'|'error' = 'success') {
  toast.value = message
  toastKind.value = kind
  window.setTimeout(() => { if (toast.value === message) toast.value = '' }, 2400)
}

function notifyError(message: string) {
  notify(message, 'error')
}

function setPage(next: Page) {
  page.value = next
  detailId.value = null; detailAsset.value = null
  relationDetailId.value = null; relationDetailData.value = null; revokeReason.value = ''
  if (next === 'relations') void loadRelations()
  if (next === 'downloads') { void loadJobs(); startJobPolling() }
  if (next === 'trash') void loadTrash()
  if (next === 'tags') void loadTags()
  if (next === 'formats') void loadFormats()
  if (next === 'admin') void loadAdmin()
}

async function openAsset(asset:Asset) {
  detailId.value = asset.id; detailAsset.value = asset
  remarkDraft.value = asset.remark || ''
  annotationSources.value = []
  selectedAnnotationSourceId.value = ''
  if (!api.session()) return
  try {
    const detail = await api.asset(String(asset.id))
    detailAsset.value = {
      ...asset,
      ...detail,
      type: assetTypeLabels[detail.type] || detail.type || asset.type,
      scene: detail.tags?.scene || '',
      algorithm: detail.tags?.algorithm || '',
      mark: detail.media?.extension || detail.mime_type || asset.mark,
      createdAt: detail.created_at ? new Date(detail.created_at).toLocaleString('zh-CN') : asset.createdAt,
      updatedAt: detail.modified_at ? new Date(detail.modified_at).toLocaleString('zh-CN') : detail.created_at ? new Date(detail.created_at).toLocaleString('zh-CN') : asset.updatedAt || asset.createdAt,
    }
    remarkDraft.value = detail.remark || ''
    if (detail.type === 'image') await loadAnnotationOverlays(String(asset.id))
  }
  catch (error) { notifyError(error instanceof Error ? error.message : '素材详情加载失败') }
}

function mapAsset(item:any, index:number):Asset {
  return {
    id:item.id, name:item.name, type:assetTypeLabels[item.type] || item.type,
    status:item.status || item.tags?.status || '', scene:item.tags?.scene || '', algorithm:item.tags?.algorithm || '',
    tone:['#9fb8c8','#2d4259','#d7a85a','#7e716d','#658b79'][index%5], mark:item.media?.extension || item.mime_type, remark:item.remark || '',
    createdAt:item.archived_at ? new Date(item.archived_at).toLocaleString('zh-CN') : item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '时间未知',
    updatedAt:item.modified_at ? new Date(item.modified_at).toLocaleString('zh-CN') : item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '时间未知',
    preview_url:item.preview_url,
    tags:item.tags || {},
  }
}

function formatStorageSize(bytes:number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 GB'
  const units=['B','KB','MB','GB','TB','PB']
  const unit=Math.min(Math.floor(Math.log(bytes)/Math.log(1024)),units.length-1)
  const value=bytes/1024**unit
  return `${value>=100?value.toFixed(0):value.toFixed(1)} ${units[unit]}`
}

function openAdjacentMedia(offset:number) {
  const target=mediaPageAssets.value[activeMediaIndex.value + offset]
  if (target) void openAsset(target)
}

function openMediaViewer() {
  if (activeAsset.value?.type === '图片' || activeAsset.value?.type === '视频') {
    pickerPreviewAsset.value = null
    mediaViewerZoom.value = 1
    mediaViewerAnnotations.value = true
    mediaViewerOpen.value = true
  }
}

function relationOriginText(source:string) {
  return ({cvat_import:'导入（图片+标注）','filename-match':'自动关联',web:'手动创建','web-model':'模型关联'} as Record<string,string>)[source] || source || '未记录'
}

async function openRelationDetail(item:any) {
  relationDetailId.value = item.id
  relationDetailData.value = item
  revokeReason.value = item.revokeReason || ''
  try {
    const detail = await api.relation(String(item.id))
    const loadMedia = async (asset:any) => {
      if (!asset || !['image','video'].includes(asset.type)) return asset
      try { return {...asset,...await api.asset(String(asset.id))} } catch { return asset }
    }
    const [sourceAsset,targetAsset] = await Promise.all([loadMedia(detail.source),loadMedia(detail.target)])
    relationDetailData.value = {...item,status:detail.status==='active'?'生效中':'已撤销',origin:relationOriginText(detail.provenance?.source),revokeReason:detail.revoke_reason || '',sourceAsset,targetAsset}
    revokeReason.value = detail.revoke_reason || ''
  } catch (error) { notifyError(error instanceof Error ? error.message : '关联详情加载失败') }
}

function openRelationMedia(asset:any) {
  if (!asset || !['image','video'].includes(asset.type)) return
  pickerPreviewAsset.value = {...asset,type:assetTypeLabels[asset.type] || asset.type}
  mediaViewerZoom.value = 1
  mediaViewerAnnotations.value = false
  mediaViewerOpen.value = true
}

async function openPickerMedia(item:any) {
  if (!['image','video'].includes(item.type)) return
  try {
    const detail = await api.asset(String(item.id))
    pickerPreviewAsset.value = {...item,...detail,type:assetTypeLabels[detail.type] || detail.type,preview_url:detail.preview_url || item.preview_url}
    mediaViewerZoom.value = 1
    mediaViewerAnnotations.value = false
    mediaViewerOpen.value = true
  } catch (error) { notifyError(error instanceof Error ? error.message : '原文件预览加载失败') }
}

function closeMediaViewer() {
  mediaViewerOpen.value = false
  pickerPreviewAsset.value = null
}

function changeMediaViewerZoom(step:number) {
  mediaViewerZoom.value = Math.min(4, Math.max(.25, Number((mediaViewerZoom.value + step).toFixed(2))))
}

async function loadAnnotationOverlays(assetId:string) {
  annotationLoading.value = true
  try {
    const result = await api.annotationOverlays(assetId)
    annotationSources.value = result.sources || []
    selectedAnnotationSourceId.value = annotationSources.value.find((source:any) => source.matched)?.annotation_asset_id || annotationSources.value[0]?.annotation_asset_id || ''
  } catch (error) {
    notifyError(error instanceof Error ? error.message : '关联标注加载失败')
  } finally { annotationLoading.value = false }
}

const activeAnnotationSource = computed(() => annotationSources.value.find((source:any) => source.annotation_asset_id === selectedAnnotationSourceId.value))
const detailMediaStyle = computed(() => {
  const width=Number(activeAsset.value?.media?.width || 0)
  const height=Number(activeAsset.value?.media?.height || 0)
  return width>0 && height>0 ? {aspectRatio:`${width} / ${height}`} : undefined
})
const originalMediaStyle = computed(() => {
  const width=Number(viewerAsset.value?.media?.width || 0)
  const height=Number(viewerAsset.value?.media?.height || 0)
  return width>0 && height>0 ? {width:`${width * mediaViewerZoom.value}px`,height:`${height * mediaViewerZoom.value}px`} : undefined
})
function annotationColor(_label:string) { return '#ef4444' }
function polygonPoints(points:Array<{x:number;y:number}>) { return points.map(point => `${point.x * 100},${point.y * 100}`).join(' ') }

async function openLineage(asset:any) {
  lineageRoot.value = asset
  lineageLoading.value = true
  page.value = 'lineage'
  detailId.value = null
  detailAsset.value = null
  try {
    const graph = await api.relationGraph(String(asset.id))
    lineageNodes.value = graph.nodes || []
    lineageEdges.value = (graph.edges || []).map((edge:any)=>({...edge,relation:relationTypeLabels[edge.relation_type]||edge.relation_type,source:edge.source_name||edge.source_id,target:edge.target_name||edge.target_id,sourceType:assetTypeLabels[edge.source_type]||edge.source_type,targetType:assetTypeLabels[edge.target_type]||edge.target_type,operator:edge.created_by_name||'系统',createdAt:edge.created_at?new Date(edge.created_at).toLocaleString('zh-CN'):'时间未知',status:edge.status==='active'?'生效中':'已撤销',origin:edge.provenance?.source||'未记录'}))
  } catch (error) {
    notifyError(error instanceof Error ? error.message : '模型溯源加载失败')
    lineageNodes.value = []
    lineageEdges.value = []
  } finally { lineageLoading.value = false }
}

async function loadRelationPicker() {
  relationPickerLoading.value = true
  const lockedType = ({'auto-image':'image','auto-annotation':'annotation',model:'model'} as Record<string,string>)[relationPickerContext.value]
  const selectedType = lockedType || relationPickerType.value
  const pageSize = relationPickerPageSize.value === 0 ? 200 : relationPickerPageSize.value
  const params = new URLSearchParams({page:String(relationPickerPage.value),page_size:String(pageSize),sort:'created_at',direction:'desc',match:relationPickerMatch.value})
  if (relationPickerQuery.value.trim()) params.set('q', relationPickerQuery.value.trim())
  if (relationPickerNoTags.value) params.set('no_tags','true')
  if (selectedType && selectedType !== 'collection') params.append('asset_type',selectedType)
  relationPickerRules.value.filter(rule=>rule.value.trim()).forEach(rule=>params.append('tag',`${rule.tag}:${rule.operator}:${serializedFilterValue(rule)}`))
  try {
    if (selectedType === 'collection') {
      const result = await api.collections()
      const keyword = relationPickerQuery.value.trim().toLocaleLowerCase()
      const items = (result.items || []).filter((item:any) => !keyword || String(item.name || '').toLocaleLowerCase().includes(keyword) || String(item.description || '').toLocaleLowerCase().includes(keyword)).map((item:any)=>({...item,type:'snapshot',remark:item.description || ''}))
      relationPickerItems.value = items
      relationPickerTotal.value = items.length
      return
    }
    let result = await api.assets(params)
    if (relationPickerPageSize.value === 0 && result.total > 200) {
      const items=[...result.items]
      for(let pageNumber=2;pageNumber<=Math.ceil(result.total/200);pageNumber+=1){ params.set('page',String(pageNumber)); const next=await api.assets(params); items.push(...next.items) }
      result={...result,items}
    }
    relationPickerItems.value = result.items
    relationPickerTotal.value = result.total
  } catch (error) { notifyError(error instanceof Error ? error.message : '素材列表加载失败') }
  finally { relationPickerLoading.value = false }
}

function selectionForPickerContext(context:string) {
  if(context==='source') return relationSourceAssets.value
  if(context==='target') return relationTargetId.value ? [{id:relationTargetId.value,name:relationTargetName.value}] : []
  if(context==='auto-image') return autoImages.value
  if(context==='auto-annotation') return autoAnnotations.value
  if(context==='model') return selectedModel.value ? [selectedModel.value] : []
  return modelTargets.value
}

function isPickerItemSelf(item:any) {
  const id = String(item?.id || '')
  if (!id) return false
  if (relationPickerContext.value === 'model-target') return id === String(selectedModel.value?.id || '')
  if (relationPickerContext.value === 'target') return relationSourceIds.value.includes(id)
  if (relationPickerContext.value === 'source') return id === String(relationTargetId.value || '')
  if (relationPickerContext.value === 'model') return modelTargets.value.some(target => String(target.id) === id)
  return false
}

async function storePickerSelection() {
  const selectedItems=relationPickerSelection.value.filter(item=>!isPickerItemSelf(item))
  if(relationPickerContext.value==='source') relationSourceAssets.value=selectedItems
  else if(relationPickerContext.value==='target') { const item=selectedItems[0]; relationTargetId.value=item ? String(item.id) : ''; relationTargetName.value=item?.name || '' }
  else if(relationPickerContext.value==='auto-image') autoImages.value=selectedItems
  else if(relationPickerContext.value==='auto-annotation') autoAnnotations.value=selectedItems
  else if(relationPickerContext.value==='model') {
    selectedModel.value=selectedItems[0] || null
    if (selectedModel.value) modelTargets.value=modelTargets.value.filter(item=>String(item.id)!==String(selectedModel.value.id))
    if (selectedModel.value && relationPickerOriginPage.value === 'lineage') await openLineage(selectedModel.value)
  }
  else modelTargets.value=selectedItems.filter(item=>String(item.id)!==String(selectedModel.value?.id))
  relationPickerOpen.value=false
}

function openAdvancedRelationPicker(context:typeof relationPickerContext.value) {
  relationPickerOriginPage.value=page.value
  relationPickerContext.value=context
  relationPickerMode.value=context==='target'||context==='model'?'target':'source'
  relationPickerQuery.value = ''
  relationPickerType.value = ''
  relationPickerNoTags.value=false
  relationPickerMatch.value='all'
  relationPickerRules.value=[]
  relationPickerPage.value = 1
  relationPickerPageSize.value=50
  relationPickerSelection.value=[...selectionForPickerContext(context)]
  relationPickerOpen.value = true
  void loadRelationPicker()
}

function openRelationPicker(mode:'source'|'target') { openAdvancedRelationPicker(mode) }

function toggleRelationSource(item:any) {
  const id = String(item.id)
  relationSourceAssets.value = relationSourceIds.value.includes(id)
    ? relationSourceAssets.value.filter(asset => String(asset.id) !== id)
    : [...relationSourceAssets.value, item]
}

function chooseRelationTarget(item:any) {
  relationTargetId.value = String(item.id)
  relationTargetName.value = item.name
  relationPickerOpen.value = false
}

async function loadLineagePicker() {
  lineagePickerLoading.value = true
  const params = new URLSearchParams({page:String(lineagePickerPage.value),page_size:'20',sort:'created_at',direction:'desc'})
  params.append('asset_type', 'model')
  if (lineagePickerQuery.value.trim()) params.set('q', lineagePickerQuery.value.trim())
  try {
    const result = await api.assets(params)
    lineagePickerItems.value = result.items
    lineagePickerTotal.value = result.total
  } catch (error) { notifyError(error instanceof Error ? error.message : '模型列表加载失败') }
  finally { lineagePickerLoading.value = false }
}

function openLineagePicker() {
  openAdvancedRelationPicker('model')
}

function chooseLineageModel(item:any) {
  lineagePickerOpen.value = false
  void openLineage({...item,type:'模型',tone:'#2d4259',mark:item.media?.extension || item.mime_type || ''})
}

function addFilterRule() {
  filterRules.value.push({ id: nextRuleId++, tag:'status', operator:'equals', value:'' })
}

function removeFilterRule(id: number) {
  if (filterRules.value.length === 1) filterRules.value = [{ id: nextRuleId++, tag:'status', operator:'equals', value:'' }]
  else filterRules.value = filterRules.value.filter((rule) => rule.id !== id)
}

function resetFilters() {
  noTags.value = false
  matchMode.value = 'all'
  filterRules.value = [{ id: nextRuleId++, tag:'status', operator:'equals', value:'' }]
  appliedMatchMode.value = 'all'
  appliedFilterRules.value = []
  selectedAssetTypes.value = []
  assetPage.value = 1
  void loadAssets()
}

function resetLibraryPage() {
  query.value = ''
  selected.value = []
  detailId.value = null
  detailAsset.value = null
  assetSort.value = 'created_at'
  assetDirection.value = 'desc'
  density.value = 'comfortable'
  resetFilters()
}

function selectedTagDefinition(key:string) {
  return tagDefinitions.value.find((tag:any) => tag.key === key)
}

function togglePickerItem(item:any) {
  if (isPickerItemSelf(item)) { notifyError('不能选择素材自身'); return }
  const id=String(item.id)
  if(relationPickerContext.value==='target'||relationPickerContext.value==='model') relationPickerSelection.value=[item]
  else relationPickerSelection.value=relationPickerSelectedIds.value.includes(id) ? relationPickerSelection.value.filter(asset=>String(asset.id)!==id) : [...relationPickerSelection.value,item]
}

function selectPickerPage() { relationPickerSelection.value=[...relationPickerSelection.value,...relationPickerItems.value.filter(item=>!isPickerItemSelf(item)&&!relationPickerSelectedIds.value.includes(String(item.id)))] }
function invertPickerPage() { const availableItems=relationPickerItems.value.filter(item=>!isPickerItemSelf(item)); const pageIds=new Set(availableItems.map(item=>String(item.id))); relationPickerSelection.value=[...relationPickerSelection.value.filter(item=>!pageIds.has(String(item.id))),...availableItems.filter(item=>!relationPickerSelectedIds.value.includes(String(item.id)))] }
function applyPickerFilters() { relationPickerSelection.value=[]; relationPickerPage.value=1; void loadRelationPicker() }
function addPickerRule() { relationPickerRules.value.push({id:nextRuleId++,tag:'status',operator:'equals',value:''}) }

function pickerFormat(item:any) {
  return item.media?.extension || (item.name?.includes('.') ? `.${item.name.split('.').pop()?.toLowerCase()}` : '') || assetTypeLabels[item.type] || item.type
}

function pickerTagsText(item:any) {
  return Object.values(item.tags || {}).flatMap(value => Array.isArray(value) ? value : [value]).filter(Boolean).join('、') || '—'
}

function selectedFilterDefinition(key:string) {
  return filterDefinitions.value.find((field:any) => field.key === key)
}

function isTimeFilter(key:string) { return key === 'created_at' || key === 'updated_at' }

function localDateTimeValue(date = new Date()) {
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return offsetDate.toISOString().slice(0,19)
}

function nextDateTimeValue(value:string) {
  const timestamp = new Date(value).getTime()
  return Number.isFinite(timestamp) ? localDateTimeValue(new Date(timestamp + 1000)) : localDateTimeValue()
}

function serializedFilterValue(rule:FilterRule) {
  if (!isTimeFilter(rule.tag)) return rule.value.trim()
  const start = new Date(rule.value).toISOString()
  return rule.operator === 'between' ? `${start}|${new Date(rule.valueEnd || '').toISOString()}` : start
}

function changeRuleTag(rule:FilterRule) {
  rule.valueEnd = undefined
  if (isTimeFilter(rule.tag)) {
    rule.operator = 'equals'
    rule.value = localDateTimeValue()
  } else {
    rule.value = ''
    if (rule.tag === 'remark' && rule.operator === 'notEquals') rule.operator = 'equals'
  }
}

function changeRuleOperator(rule:FilterRule) {
  if (rule.operator === 'between') rule.valueEnd = nextDateTimeValue(rule.value || localDateTimeValue())
  else rule.valueEnd = undefined
}

function toggleAssetType(type:string) {
  selectedAssetTypes.value = selectedAssetTypes.value.includes(type)
    ? selectedAssetTypes.value.filter(item => item !== type)
    : [...selectedAssetTypes.value, type]
  assetPage.value = 1
  void loadAssets()
}

function applyAssetFilters() { assetPage.value = 1; void loadAssets() }
function applyAdvancedFilters() {
  const invalidRange = filterRules.value.find(rule => rule.operator === 'between' && (!rule.valueEnd || new Date(rule.valueEnd).getTime() <= new Date(rule.value).getTime()))
  if (invalidRange) { notifyError('结束时间必须晚于开始时间'); return }
  appliedMatchMode.value=matchMode.value
  appliedFilterRules.value=filterRules.value.filter(rule=>rule.value.trim()).map(rule=>({...rule}))
  selected.value=[]
  applyAssetFilters()
}
function changeAssetPage(page:number) { assetPage.value = page; void loadAssets() }

async function login() {
  loginBusy.value = true
  loginError.value = ''
  try {
    const result = await api.login(loginUsername.value, loginPassword.value)
    currentUser.value = result.user
    showLogin.value = false
    await Promise.all([loadAssets(), loadJobs(), loadTrash()])
  } catch (error) {
    loginError.value = error instanceof Error ? error.message : '登录失败'
  } finally { loginBusy.value = false }
}

async function logout() {
  await api.logout()
  currentUser.value = null
  showLogin.value = true
}

async function loadAssets() {
  if (!api.session()) return
  demoState.value = 'loading'
  try {
    const assetsRequest = assetPageSize.value === 0
      ? loadAllAssetPages()
      : api.assets(assetListParams(assetPage.value, effectiveAssetPageSize.value))
    const [result, views, stats, tags] = await Promise.all([assetsRequest, api.savedViews(), api.assetStats(), api.tags()])
    assetFilteredTotal.value = result.total
    assetTotal.value = stats.total
    untaggedTotal.value = stats.untagged
    assetTypeCounts.value = stats.by_type
    storageStats.value = stats.storage
    tagRows.value = tags.items
    assets.value = result.items.map(mapAsset)
    demoState.value = result.items.length ? 'normal' : 'empty'
    savedViewRows.value = views.items
  } catch (error) {
    demoState.value = 'error'
    notifyError(error instanceof Error ? error.message : '素材加载失败')
  }
}

function canDisplayMediaPreview(asset: Pick<Asset, 'type' | 'preview_url'> | null | undefined) {
  return Boolean(asset?.preview_url) && (asset?.type === '图片' || asset?.type === '视频')
}

function applySavedView(view:any) {
  const value = view.query || {}
  query.value = value.q || ''; noTags.value = Boolean(value.no_tags); matchMode.value = value.match || 'all'
  selectedAssetTypes.value = Array.isArray(value.asset_types) ? value.asset_types : []
  filterRules.value = (value.tags?.length ? value.tags : [{tag:'status',operator:'equals',value:''}]).map((rule:any) => ({...rule,id:nextRuleId++}))
  appliedMatchMode.value=matchMode.value
  appliedFilterRules.value=filterRules.value.filter(rule=>rule.value.trim()).map(rule=>({...rule}))
  const savedSort = view.sort?.[0]
  if (savedSort) {
    assetSort.value = Object.keys(savedSort)[0] || 'created_at'
    assetDirection.value = Object.values(savedSort)[0] === 'asc' ? 'asc' : 'desc'
  }
  assetPage.value = 1
  void loadAssets()
}

async function createCollection() {
  if (!selected.value.length || !collectionName.value.trim()) { notifyError('请填写名称并选择素材'); return }
  try {
    await api.createCollection({name:collectionName.value.trim(),description:collectionDescription.value,asset_ids:selected.value.map(String),freeze:collectionFreeze.value})
    collectionOpen.value=false; collectionName.value=''; collectionDescription.value=''
    notify(collectionFreeze.value ? '已创建不可变数据集快照' : '已创建素材集合')
  } catch (error) { notifyError(error instanceof Error ? error.message : '创建集合失败') }
}

function chooseFile(event: Event) {
  const input = event.target as HTMLInputElement
  const incoming = Array.from(input.files || [])
  const merged = new Map(uploadFiles.value.map(file => [uploadFileKey(file), file]))
  incoming.forEach(file => merged.set(uploadFileKey(file), file))
  uploadFiles.value = Array.from(merged.values())
  incoming.forEach(file => { uploadTypeOverrides.value[uploadFileKey(file)] = detectAssetType(file) })
  input.value = ''
  uploadError.value = ''
}

const uploadTypeLabels:Record<string,string> = {image:'图片',video:'视频',annotation:'标注',model:'模型',archive:'压缩文件',image_annotation:'图片+标注',other:'其他'}
function detectAssetType(file:File) {
  const extension = `.${file.name.split('.').pop()?.toLowerCase() || ''}`
  const configured = formatRows.value.find(row => (row.extensions || []).includes(extension))
  return configured?.asset_type || ''
}
function uploadFileKey(file:File) { return `${file.name}:${file.size}:${file.lastModified}` }
function resolvedUploadType(file:File) { return uploadTypeOverrides.value[uploadFileKey(file)] || detectAssetType(file) || '' }
function uploadTypeStatus(file:File) {
  const detected = detectAssetType(file)
  const selected = resolvedUploadType(file)
  if (!selected) return '类型未识别'
  if (selected === 'image_annotation') return '上传后会解压并创建关联关系'
  return detected === selected ? `自动识别为${uploadTypeLabels[selected]}` : `已调整为${uploadTypeLabels[selected]}`
}
function removeUploadFile(file:File) {
  uploadFiles.value = uploadFiles.value.filter(item => uploadFileKey(item) !== uploadFileKey(file))
  delete uploadTypeOverrides.value[uploadFileKey(file)]
}
function openUpload() {
  void loadFormats()
  uploadFiles.value = []; uploadTypeOverrides.value = {}; uploadTags.value={}; uploadError.value = ''; uploadProgress.value = 0; uploadOpen.value = true
}

async function uploadAsset() {
  if (!uploadFiles.value.length) { uploadError.value = '请选择文件'; return }
  const unresolved = uploadFiles.value.filter(file => !resolvedUploadType(file))
  if (unresolved.length) { uploadError.value = `请为 ${unresolved.map(file=>file.name).join('、')} 选择资产类型`; return }
  uploadBusy.value = true; uploadProgress.value = 5; uploadError.value = ''
  const files = [...uploadFiles.value]
  const failed:Array<{file:File;message:string}> = []
  let succeeded = 0
  let hasDatasetPackage = false
  try {
    for (let index=0; index<files.length; index++) {
      const file = files[index]
      try {
        const session = await api.initUpload({filename:file.name,size:file.size,mime_type:file.type || 'application/octet-stream',asset_type:resolvedUploadType(file)})
        if (session.upload_required) {
          const response = await fetch(session.upload_url, {method:'PUT',body:file})
          if (!response.ok) throw new Error('文件上传到对象存储失败')
        }
        await api.completeUpload({upload_session_id:session.upload_session_id,tags:{...uploadTags.value}})
        succeeded += 1
        hasDatasetPackage ||= resolvedUploadType(file) === 'image_annotation'
      } catch (error) {
        failed.push({file,message:error instanceof Error ? error.message : '上传失败'})
      }
      uploadProgress.value = Math.round(((index + 1) / files.length) * 100)
    }
    if (failed.length) {
      uploadFiles.value = failed.map(item => item.file)
      uploadError.value = failed.map(item => `${item.file.name}：${item.message}`).join('；')
      notify(`已上传 ${succeeded} 个，失败 ${failed.length} 个`, 'error')
    } else {
      uploadOpen.value = false; uploadFiles.value = []; uploadTypeOverrides.value = {}; uploadTags.value={}
      notify(hasDatasetPackage ? `已上传 ${succeeded} 个文件，数据集包正在解压并建立关联` : `已上传 ${succeeded} 个文件，正在生成预览`)
    }
    await loadAssets()
  } catch (error) { uploadError.value = error instanceof Error ? error.message : '批量上传失败' }
  finally { uploadBusy.value = false }
}

onMounted(() => { if (api.session()) void Promise.all([loadAssets(), loadJobs(), loadFormats(), loadTrash()]); startJobPolling() })

async function loadRelations() {
  if (!api.session()) return
  try {
    const filters:Record<string,string>={}
    if(relationHistoryQuery.value.trim()) filters.q=relationHistoryQuery.value.trim()
    if(relationHistoryType.value) filters.relation_type=relationHistoryType.value
    if(relationHistoryStatus.value) filters.status=relationHistoryStatus.value
    if(relationHistoryCreator.value.trim()) filters.created_by=relationHistoryCreator.value.trim()
    if(relationHistoryFrom.value) filters.created_from=new Date(relationHistoryFrom.value).toISOString()
    if(relationHistoryTo.value) filters.created_to=new Date(relationHistoryTo.value).toISOString()
    const result = await api.relations(relationPage.value, relationPageSize.value,filters)
    relationTotal.value = result.total
    relationHistory.value = result.items.map((item:any) => ({
      id:item.id, source:item.source_name || item.source_id, relation:relationTypeLabels[item.relation_type] || item.relation_type,
      target:item.target_name || item.target_id, operator:item.created_by_name || '系统', createdAt:new Date(item.created_at).toLocaleString('zh-CN'),
      status:item.status === 'active' ? '生效中' : '已撤销', sourceType:assetTypeLabels[item.source_type] || (item.source_type === 'snapshot' ? '数据集' : '资产'), targetType:assetTypeLabels[item.target_type] || (item.target_type === 'snapshot' ? '数据集' : '资产'),
      origin:relationOriginText(item.provenance?.source), revokeReason:item.revoke_reason || '',
      sourceId:item.source_id, targetId:item.target_id,
    }))
  } catch (error) { notifyError(error instanceof Error ? error.message : '关联记录加载失败') }
}

function openSaveView() {
  const now = new Date()
  const pad = (value:number) => String(value).padStart(2, '0')
  const stamp = `${now.getFullYear()}${pad(now.getMonth()+1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  editingViewId.value = null
  savedViewName.value = `筛选视图-${stamp}`
  savedViewOpen.value = true
}

function openRenameView(view:any) {
  editingViewId.value = String(view.id)
  savedViewName.value = view.name
  savedViewOpen.value = true
}

async function saveCurrentView() {
  if (!savedViewName.value.trim()) { notifyError('请输入视图名称'); return }
  try {
    if (editingViewId.value) await api.updateSavedView(editingViewId.value, savedViewName.value.trim())
    else await api.createSavedView({name:savedViewName.value.trim(),query:{q:query.value,no_tags:noTags.value,match:appliedMatchMode.value,asset_types:selectedAssetTypes.value,tags:appliedFilterRules.value},sort:[{[assetSort.value]:assetDirection.value}],fields:[],shared:false})
    savedViewOpen.value = false
    notify(editingViewId.value ? '视图名称已修改' : '已保存当前筛选视图')
    await loadAssets()
  } catch (error) { notifyError(error instanceof Error ? error.message : '保存视图失败') }
}

function removeSavedView(id:string, name:string) {
  askConfirmation(`确定要删除保存视图“${name}”吗？`, async () => {
    await api.deleteSavedView(id); notify('保存视图已删除'); await loadAssets()
  })
}

async function exportSelected() {
  if (!selected.value.length) return
  try {
    const current = new Date()
    const part = (value:number) => String(value).padStart(2, '0')
    const timestamp = `${current.getFullYear()}${part(current.getMonth()+1)}${part(current.getDate())}_${part(current.getHours())}${part(current.getMinutes())}${part(current.getSeconds())}`
    await api.createExport({name:`素材导出_${timestamp}`,asset_ids:selected.value.map(String)})
    notify('导出任务已加入下载中心')
  } catch (error) { notifyError(error instanceof Error ? error.message : '创建导出任务失败') }
}

async function submitRelations() {
  if (!relationSourceIds.value.length || !relationTargetId.value.trim()) { notifyError('请先选择源素材和目标素材'); return }
  try {
    relationPreview.value=await api.previewRelations({relations:relationSourceIds.value.map(id=>({source_id:id,target_id:relationTargetId.value.trim(),relation_type:relationType.value,provenance:{source:'web'}}))})
    relationPreviewKind.value='general'; relationPreviewOpen.value=true
  } catch (error) { notifyError(error instanceof Error ? error.message : '关系预览失败') }
}

async function previewAutoRelations() {
  try { relationPreview.value=await api.previewAnnotationMatches({}); relationPreviewKind.value='auto'; relationPreviewOpen.value=true }
  catch(error){ notifyError(error instanceof Error?error.message:'自动匹配预览失败') }
}

async function resetRelationHistoryFilters() {
  relationHistoryQuery.value = ''
  relationHistoryType.value = ''
  relationHistoryStatus.value = ''
  relationHistoryCreator.value = ''
  relationHistoryFrom.value = ''
  relationHistoryTo.value = ''
  relationPage.value = 1
  await loadRelations()
}

async function previewModelRelations() {
  if(!selectedModel.value||!modelTargets.value.length){ notifyError('请先选择模型和需要关联的素材'); return }
  try { relationPreview.value=await api.previewRelations({relations:modelTargets.value.filter(item=>String(item.id)!==String(selectedModel.value.id)).map(item=>({source_id:String(selectedModel.value.id),target_id:String(item.id),relation_type:relationType.value,provenance:{source:'web-model'}}))}); relationPreviewKind.value='general'; relationPreviewOpen.value=true }
  catch(error){ notifyError(error instanceof Error?error.message:'模型关系预览失败') }
}

async function confirmRelationPreview() {
  const ready=relationPreview.value?.ready || []
  if(!ready.length){ notifyError('没有可以建立的关系'); return }
  relationSubmitting.value=true
  try {
    const relations=relationPreviewKind.value==='auto' ? ready.map((item:any)=>({source_id:String(item.source.id),target_id:String(item.target.id),relation_type:'annotates',provenance:{source:'filename-match'}})) : ready.map((item:any)=>item.relation)
    const batches=relationPreviewKind.value==='auto' ? Array.from({length:Math.ceil(relations.length/5000)},(_,index)=>relations.slice(index*5000,(index+1)*5000)) : [relations]
    const results=[]
    for(const batch of batches) results.push(await api.createRelations({relations:batch}))
    const succeeded=results.flatMap((result:any)=>result.succeeded||[])
    const failed=results.flatMap((result:any)=>result.failed||[])
    notify(relationPreviewKind.value==='auto' ? `本次 ${succeeded.length} 组图片与标注自动关联成功` : `已建立 ${succeeded.length} 条关系，${failed.length} 条未建立`)
    relationPreviewOpen.value=false
    if(relationWorkflow.value==='auto'){ autoImages.value=[];autoAnnotations.value=[] }
    else if(relationWorkflow.value==='model'){ modelTargets.value=[] }
    else { relationSourceAssets.value=[];relationTargetId.value='';relationTargetName.value='' }
    await loadRelations()
  } catch(error){ notifyError(error instanceof Error?error.message:'建立关系失败') }
  finally{ relationSubmitting.value=false }
}

async function loadJobs() {
  try { const result = await api.jobs('export'); jobRows.value = result.items; jobTotal.value = result.total }
  catch (error) { notifyError(error instanceof Error ? error.message : '任务加载失败') }
}

function startJobPolling() {
  if (jobPoll !== null) window.clearInterval(jobPoll)
  jobPoll = window.setInterval(async () => {
    if (page.value === 'downloads') void loadJobs()
    if (page.value === 'library' && assets.value.some(asset => ['queued','processing'].includes(asset.status))) {
      const detailStatus = detailAsset.value?.status
      const detailAssetId = detailAsset.value?.id
      await loadAssets()
      const refreshed = assets.value.find(asset => asset.id === detailAssetId)
      if (refreshed && refreshed.status !== detailStatus) await openAsset(refreshed)
    }
  }, 3000)
}

function showDetailScrollbar() {
  detailSheetScrolling.value = true
  if (detailScrollTimer !== null) window.clearTimeout(detailScrollTimer)
  detailScrollTimer = window.setTimeout(() => {
    detailSheetScrolling.value = false
    detailScrollTimer = null
  }, 700)
}

onBeforeUnmount(() => {
  if (jobPoll !== null) window.clearInterval(jobPoll)
  if (detailScrollTimer !== null) window.clearTimeout(detailScrollTimer)
})

async function downloadExport(id:string) {
  try { window.open((await api.exportDownload(id)).download_url, '_blank', 'noopener') }
  catch (error) { notifyError(error instanceof Error ? error.message : '下载失败') }
}

async function loadTags() {
  try { tagRows.value = (await api.tags()).items }
  catch (error) { notifyError(error instanceof Error ? error.message : '标签加载失败') }
}

async function createTag() {
  try {
    const body = {name:newTag.value.name.trim(),values:tagValueRows.value.map(item=>item.value.trim()).filter(Boolean),color:newTag.value.color,asset_types:[],free_input:newTag.value.free_input}
    if (editingTagKey.value) await api.updateTag(editingTagKey.value, body)
    else await api.createTag({...body,key:newTag.value.key.trim()})
    tagOpen.value=false; editingTagKey.value=null; tagValueRows.value=[]; newTag.value={name:'',key:'',values:'',color:'#64748b',free_input:false}; notify('标签字段已保存'); await loadTags()
  } catch (error) { notifyError(error instanceof Error ? error.message : '创建标签失败') }
}

function setTagValueRows(values:string[]) { tagValueRows.value=values.map(value=>({id:nextTagValueId++,value,editing:false})) }
function addTagValue() { tagValueRows.value.push({id:nextTagValueId++,value:'',editing:true}) }
function removeTagValue(id:number) {
  const row = tagValueRows.value.find(item => item.id === id)
  askConfirmation(`确定要删除标签值“${row?.value || '未命名'}”吗？`, () => {
    tagValueRows.value=tagValueRows.value.filter(item=>item.id!==id)
  })
}
function toggleTagValueEdit(row:{id:number;value:string;editing:boolean}) { row.editing=!row.editing }
function applyPickerColor() { newTag.value.color=tagPickerColor.value }
function openNewTag() { editingTagKey.value=null; newTag.value={name:'',key:'',values:'',color:'#64748b',free_input:false}; tagPickerColor.value='#64748b'; setTagValueRows([]); tagOpen.value=true }
function openEditTag(tag:any) { editingTagKey.value=tag.key; newTag.value={name:tag.name,key:tag.key,values:'',color:tag.color || '#64748b',free_input:Boolean(tag.free_input)}; tagPickerColor.value=tag.color || '#64748b'; setTagValueRows(tag.values||[]); tagOpen.value=true }

function removeTag(key:string, name:string) {
  askConfirmation(`确定要删除标签“${name}”吗？`, async () => {
    await api.deleteTag(key); notify('标签字段已删除'); await loadTags()
  })
}

function deleteSelectedAssets() {
  const ids = selected.value.map(String)
  if (!ids.length) return
  askConfirmation(`确定要删除${ids.length}项吗？`, async () => {
    const result = await api.batchDelete(ids)
    selected.value = result.failed.map((item:any) => item.id)
    detailId.value = null; detailAsset.value = null
    const failedMessage = result.failed.map((item:any) => item.message || item.code).join('；')
    notify(result.failed.length ? `已移入回收站 ${result.succeeded.length} 项，${result.failed.length} 项失败：${failedMessage}` : `已将 ${result.succeeded.length} 项素材移入回收站`, result.failed.length ? 'error' : 'success')
    await loadAssets()
  })
}

async function loadTrash() {
  try {
    let result = await api.trash(trashPage.value, effectiveTrashPageSize.value)
    if (trashPageSize.value === 0) {
      const items = [...result.items]
      const pageCount = Math.ceil(result.total / 200)
      for (let pageNumber = 2; pageNumber <= pageCount; pageNumber += 1) {
        const next = await api.trash(pageNumber, 200)
        items.push(...next.items)
      }
      result = {...result,items}
    }
    trashAssets.value = result.items.map(mapAsset)
    trashTotal.value = result.total
    trashSelected.value = trashSelected.value.filter(id => trashAssets.value.some(asset => asset.id === id))
  } catch (error) { notifyError(error instanceof Error ? error.message : '回收站加载失败') }
}

function toggleTrashSelect(id:AssetId) {
  trashSelected.value = trashSelected.value.includes(id) ? trashSelected.value.filter(item => item !== id) : [...trashSelected.value,id]
}

function selectTrashPage() { trashSelected.value = trashAssets.value.map(asset => asset.id) }
function invertTrashPage() { trashSelected.value = trashAssets.value.filter(asset => !trashSelected.value.includes(asset.id)).map(asset => asset.id) }

function restoreTrashAssets() {
  const ids=trashSelected.value.map(String)
  if(!ids.length) return
  askConfirmation(`确定要还原${ids.length}项吗？`,async()=>{
    const result=await api.restoreTrash(ids)
    trashSelected.value=result.failed.map((item:any)=>item.id)
    notify(`已还原 ${result.succeeded.length} 项素材`)
    await Promise.all([loadTrash(),loadAssets()])
  })
}

function emptyTrash() {
  if(!trashTotal.value) return
  askConfirmation(`确定要清空回收站中的${trashTotal.value}项吗？`,async()=>{
    const job=await api.emptyTrash()
    trashSelected.value=[]
    notify('已提交后台清理')
    void monitorTrashJob(String(job.id))
  })
}

async function monitorTrashJob(jobId:string) {
  for (let attempt=0;attempt<120;attempt+=1) {
    await new Promise(resolve=>window.setTimeout(resolve,1000))
    try {
      const job=await api.job(jobId)
      if(job.state==='succeeded') {
        const failed=job.result?.failed?.length || 0
        notify(failed?`回收站清理完成，${failed} 项失败`:'回收站已清空', failed ? 'error' : 'success')
        await Promise.all([loadTrash(),loadAssets()])
        return
      }
      if(job.state==='failed') { notifyError(job.error?.message || '回收站清理失败'); return }
    } catch { return }
  }
}

function assetTagValues(asset:any) {
  return Object.values(asset.tags || {}).flatMap(value => Array.isArray(value) ? value : [value]).filter(Boolean).slice(0,2)
}

function assetTagEntries(asset:any) {
  return Object.entries(asset.tags || {}).flatMap(([key,raw]) => {
    const values = Array.isArray(raw) ? raw : [raw]
    const label = tagDefinitions.value.find((tag:any) => tag.key === key)?.label || key
    return values.filter(Boolean).map(value => ({key,label,value:String(value)}))
  })
}

async function saveAssetRemark() {
  if (!activeAsset.value || remarkSaving.value) return
  remarkSaving.value = true
  try {
    const updated = await api.updateAssetRemark(String(activeAsset.value.id), remarkDraft.value)
    detailAsset.value = {...detailAsset.value,remark:updated.remark || '',updatedAt:updated.modified_at ? new Date(updated.modified_at).toLocaleString('zh-CN') : detailAsset.value.updatedAt}
    notify('备注已保存')
    await loadAssets()
  } catch (error) { notifyError(error instanceof Error ? error.message : '备注保存失败') }
  finally { remarkSaving.value = false }
}

async function removeAssetTag(key:string, value:string) {
  if (!activeAsset.value) return
  try {
    await api.batchTags({asset_ids:[String(activeAsset.value.id)],set_tags:{},remove_tags:[],remove_tag_values:{[key]:[value]}})
    notify('标签已删除')
    const current = assets.value.find(asset => String(asset.id) === String(activeAsset.value?.id)) || activeAsset.value
    await loadAssets()
    await openAsset(current)
  } catch (error) { notifyError(error instanceof Error ? error.message : '删除标签失败') }
}

function processingStatusText(status:string) {
  return ({queued:'等待处理',processing:'处理中',ready:'已就绪',failed:'处理失败',archived:'已删除'} as Record<string,string>)[status] || status || '状态未知'
}

function jobTypeText(type:string) { return jobTypeLabels[type] || type }
function jobStateText(state:string) { return jobStateLabels[state] || state }
function roleText(role:string) { return roleLabels[role] || role }
function userStatusText(status:string) { return userStatusLabels[status] || status }
function auditActionText(action:string) { return auditActionLabels[action] || action }

async function retryJob(id:string) {
  try { await api.retryJob(id); notify('任务已重新提交'); await loadJobs() }
  catch (error) { notifyError(error instanceof Error ? error.message : '任务重试失败') }
}

async function loadAdmin() {
  try { userRows.value=(await api.users()).items }
  catch (error) { notifyError(error instanceof Error ? error.message : '管理数据加载失败') }
}

async function createUser() {
  if (newUser.value.username.trim().length < 3) { notifyError('用户名至少需要 3 个字符'); return }
  if (!editingUserId.value && newUser.value.password.length < 8) { notifyError('初始密码至少需要 8 个字符'); return }
  if (editingUserId.value && newUser.value.password && newUser.value.password.length < 8) { notifyError('新密码至少需要 8 个字符'); return }
  try {
    const body = {username:newUser.value.username.trim(),roles:[newUser.value.role],status:newUser.value.status,...(newUser.value.password?{password:newUser.value.password}:{})}
    if (editingUserId.value) await api.updateUser(editingUserId.value,body)
    else await api.createUser(body)
    const message = editingUserId.value ? '用户已更新' : '用户已创建'
    userOpen.value=false; editingUserId.value=null; newUser.value={username:'',password:'',role:'viewer',status:'active'}; notify(message); await loadAdmin()
  } catch (error) { notifyError(error instanceof Error ? error.message : '保存用户失败') }
}

function openNewUser() { editingUserId.value=null; newUser.value={username:'',password:'',role:'viewer',status:'active'}; userOpen.value=true }
function openEditUser(user:any) { if(user.username==='admin') return; editingUserId.value=String(user.id); newUser.value={username:user.username,password:'',role:user.roles[0]||'viewer',status:user.status||'active'}; userOpen.value=true }
function removeUser(user:any) { if(user.username==='admin') return; askConfirmation(`确定要删除用户“${user.username}”吗？`,async()=>{await api.deleteUser(String(user.id));notify('用户已删除');await loadAdmin()}) }

async function loadFormats() {
  try {
    const order = manageableFormatTypes
    formatRows.value=(await api.formats()).items.sort((a:any,b:any)=>order.indexOf(a.asset_type)-order.indexOf(b.asset_type))
  }
  catch (error) { notifyError(error instanceof Error ? error.message : '格式配置加载失败') }
}
function openNewFormat() { if(!availableFormatTypes.value.length){notify('图片、视频、标注和模型格式均已创建');return};editingFormatType.value='';newFormatType.value=availableFormatTypes.value[0];formatRemark.value='';formatValueRows.value=[];formatOpen.value=true }
function openEditFormat(row:any) { const protectedValues=new Set(row.protected_extensions||[]);editingFormatType.value=row.asset_type;formatRemark.value=row.remark||'';formatValueRows.value=(row.extensions||[]).map((value:string)=>({id:nextFormatValueId++,value,editing:false,protected:protectedValues.has(value)}));formatOpen.value=true }
function addFormatValue() { formatValueRows.value.push({id:nextFormatValueId++,value:'',editing:true,protected:false}) }
function removeFormatValue(id:number) { formatValueRows.value=formatValueRows.value.filter(row=>row.id!==id) }
function toggleFormatValueEdit(row:{editing:boolean}) { row.editing=!row.editing }
async function saveFormat() { try { const body={remark:formatRemark.value.trim(),extensions:formatValueRows.value.map(row=>row.value.trim()).filter(Boolean)};if(editingFormatType.value)await api.updateFormat(editingFormatType.value,body);else await api.createFormat({...body,asset_type:newFormatType.value});formatOpen.value=false;notify('格式配置已保存');await loadFormats() } catch(error){notifyError(error instanceof Error?error.message:'保存格式失败')} }
function removeFormat(row:any) { askConfirmation(`确定要删除“${assetTypeLabels[row.asset_type]}”格式类别吗？`,async()=>{await api.deleteFormat(row.asset_type);notify('格式类别已删除');await loadFormats()}) }

async function applyBatchTag() {
  if (!batchTagValue.value.trim()) { notifyError('请输入标签值'); return }
  if (batchTagTarget.value === 'upload') {
    const value=batchTagValue.value.trim()
    const current=uploadTags.value[batchTagKey.value] || []
    if (!current.includes(value)) uploadTags.value={...uploadTags.value,[batchTagKey.value]:[...current,value]}
    batchTagOpen.value=false
    return
  }
  try {
    const value = batchTagValue.value.trim()
    const body = batchTagAction.value === 'add'
      ? {asset_ids:selected.value.map(String),set_tags:{[batchTagKey.value]:value},remove_tags:[],remove_tag_values:{}}
      : {asset_ids:selected.value.map(String),set_tags:{},remove_tags:[],remove_tag_values:{[batchTagKey.value]:[value]}}
    const result = await api.batchTags(body)
    notify(`已${batchTagAction.value === 'add' ? '添加' : '删除'} ${result.succeeded.length} 项素材的标签`)
    batchTagOpen.value = false
    await loadAssets()
  } catch (error) { notifyError(error instanceof Error ? error.message : '批量标签失败') }
}

function openBatchTag(target:'library'|'upload', action:'add'|'remove'='add') {
  batchTagTarget.value=target
  batchTagAction.value=action
  batchTagKey.value=tagDefinitions.value[0]?.key || ''
  batchTagValue.value=''
  batchTagOpen.value=true
}

function removeUploadTag(key:string, value:string) {
  const next={...uploadTags.value}
  const remaining=(next[key] || []).filter(item=>item!==value)
  if (remaining.length) next[key]=remaining
  else delete next[key]
  uploadTags.value=next
}

async function revokeActiveRelation() {
  if (!activeRelation.value) return
  const relation = {...activeRelation.value}
  try {
    await api.revokeRelation(String(relation.id), revokeReason.value.trim())
    notify('关联关系已撤销')
    await loadRelations()
    if(page.value==='lineage'&&lineageRoot.value) await openLineage(lineageRoot.value)
    await openRelationDetail(relation)
  } catch (error) { notifyError(error instanceof Error ? error.message : '撤销失败') }
}
</script>

<template>
  <div class="prototype variant-a" :class="[`skin-${skin}`, `density-${density}`]">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">VA</span><span>视觉资产库</span></div>
      <label class="global-search"><span>⌕</span><input v-model="query" placeholder="搜索名称、备注、标签、算法…" @keyup.enter="applyAssetFilters" /></label>
      <div class="header-actions">
        <label class="skin-picker"><span>界面</span><select v-model="skin"><option value="light">白天模式</option><option value="command">夜间模式</option></select></label>
        <button class="icon-button" aria-label="通知">◌</button>
        <button class="profile"><span>{{ String(currentUser?.username || '管').slice(0,1) }}</span><b>{{ currentUser?.username || '未登录' }}</b><small>{{ currentUser?.roles?.[0] || '管理员' }}</small></button>
        <button v-if="currentUser" class="logout-button" @click="logout">退出</button>
      </div>
    </header>

    <aside class="sidebar">
      <nav>
        <div class="nav-label">资产管理</div>
        <button :class="{ active: page === 'library' }" @click="setPage('library')"><span>▦</span>素材库<em>{{assetTotal}}</em></button>
        <button :class="{ active: page === 'relations' }" @click="setPage('relations')"><span>⌁</span>关联关系</button>
        <button :class="{ active: page === 'lineage' }" @click="setPage('lineage')"><span>⑂</span>模型溯源</button>
        <button :class="{ active: page === 'downloads' }" @click="setPage('downloads')"><span>⇩</span>下载中心<em>{{jobTotal}}</em></button>
        <button :class="{ active: page === 'trash' }" @click="setPage('trash')"><span>♲</span>回收站<em>{{trashTotal || ''}}</em></button>
        <div class="nav-label">系统管理</div>
        <button :class="{ active: page === 'tags' }" @click="setPage('tags')"><span>◇</span>标签管理</button>
        <button :class="{ active: page === 'formats' }" @click="setPage('formats')"><span>◫</span>格式管理</button>
        <button :class="{ active: page === 'admin' }" @click="setPage('admin')"><span>⚙</span>用户管理</button>
      </nav>
      <div class="storage">
        <div><span>存储空间</span><b>剩余 {{storageFreePercent}}%</b></div>
        <div class="meter"><i :style="{width:`${storageUsedPercent}%`}"></i></div>
        <small>{{formatStorageSize(storageStats.free)}} 可用 / 共 {{formatStorageSize(storageStats.total)}}</small>
      </div>
    </aside>

    <main>
      <template v-if="page === 'library'">
        <section class="page-head">
          <div><h1>素材库</h1></div>
          <div class="primary-actions"><button v-if="selected.length" class="secondary" @click="selected=[]">× 取消选择</button><button class="secondary" :disabled="!filtered.length || allCurrentSelected" @click="selectCurrentPage">✓ 全选</button><button class="secondary" :disabled="!filtered.length" @click="invertCurrentPageSelection">⇄ 反选</button><button class="secondary" @click="resetLibraryPage">↻ 重置页面</button><button class="secondary" @click="openSaveView">☆ 保存视图</button><button class="primary" @click="openUpload">＋ 上传素材</button></div>
        </section>

        <div class="library-shell">
          <aside class="filters">
            <div class="filter-title"><b>筛选器</b><button @click="resetFilters">重置</button></div>
            <label>资产类型</label>
            <div class="check-list"><button v-for="item in [{key:'image',label:'图片'},{key:'video',label:'视频'},{key:'annotation',label:'标注'},{key:'model',label:'模型'},{key:'archive',label:'压缩文件'},{key:'other',label:'其他'}]" :key="item.key" :class="{active:selectedAssetTypes.includes(item.key)}" @click="toggleAssetType(item.key)"><i>{{selectedAssetTypes.includes(item.key)?'✓':'○'}}</i><span>{{item.label}}</span><b>{{assetTypeCounts[item.key] || 0}}</b></button></div>
            <button class="untagged-filter" :class="{active:noTags}" @click="noTags=!noTags;applyAssetFilters()"><span>◇</span><b>无标签</b><em>{{untaggedTotal}}</em><i>{{ noTags ? '✓' : '' }}</i></button>
            <div class="advanced-head"><div><b>高级筛选条件</b><small>多个条件可组合</small></div><button @click="addFilterRule">＋ 条件</button></div>
            <div class="match-mode"><span>符合</span><button :class="{active:matchMode==='all'}" @click="matchMode='all'">全部条件</button><button :class="{active:matchMode==='any'}" @click="matchMode='any'">任一条件</button></div>
            <div class="filter-rules">
              <div v-for="(rule,index) in filterRules" :key="rule.id" class="filter-rule">
                <div class="rule-number">{{ index === 0 ? '当' : matchMode === 'all' ? '且' : '或' }}</div>
                <select v-model="rule.tag" aria-label="标签名称" @change="changeRuleTag(rule)"><option v-for="tag in filterDefinitions" :key="tag.key" :value="tag.key">{{tag.label}}</option></select>
                <select v-model="rule.operator" aria-label="筛选条件" @change="changeRuleOperator(rule)"><template v-if="isTimeFilter(rule.tag)"><option value="equals">等于</option><option value="lt">小于</option><option value="gt">大于</option><option value="between">位于</option></template><template v-else><option value="equals">等于</option><option v-if="rule.tag!=='remark'" value="notEquals">不等于</option><option value="contains">包含</option><option value="notContains">不包含</option></template></select>
                <div v-if="isTimeFilter(rule.tag)" class="filter-time-values" :class="{range:rule.operator==='between'}"><input v-model="rule.value" type="datetime-local" step="1" aria-label="开始时间" @change="rule.operator==='between' && rule.valueEnd && new Date(rule.valueEnd).getTime() <= new Date(rule.value).getTime() ? rule.valueEnd=nextDateTimeValue(rule.value) : null" /><span v-if="rule.operator==='between'">至</span><input v-if="rule.operator==='between'" v-model="rule.valueEnd" type="datetime-local" step="1" :min="nextDateTimeValue(rule.value)" aria-label="结束时间" /></div>
                <select v-else-if="selectedFilterDefinition(rule.tag)?.values?.length && !selectedFilterDefinition(rule.tag)?.free_input" v-model="rule.value" aria-label="标签值"><option value="" disabled>请选择</option><option v-for="value in selectedFilterDefinition(rule.tag)?.values" :key="value" :value="value">{{value}}</option></select>
                <input v-else v-model="rule.value" placeholder="请输入值" aria-label="标签值" />
                <button class="remove-rule" aria-label="移除条件" @click="removeFilterRule(rule.id)">×</button>
              </div>
              <datalist id="tag-values"><template v-for="tag in tagDefinitions" :key="tag.key"><option v-for="value in tag.values" :key="`${tag.key}-${value}`" :value="value" /></template></datalist>
            </div>
            <button class="apply-filter" @click="applyAdvancedFilters">应用筛选</button>
            <div class="saved"><b>已保存视图</b><div v-for="view in savedViewRows" :key="view.id" class="saved-row"><button class="saved-name" @click="applySavedView(view)">{{view.name}}</button><button class="saved-icon" title="修改名称" aria-label="修改视图名称" @click="openRenameView(view)">✎</button><button class="saved-icon delete" title="删除" aria-label="删除保存视图" @click="removeSavedView(String(view.id),view.name)">×</button></div><small v-if="!savedViewRows.length">暂无保存视图</small></div>
          </aside>

          <section class="content-panel">
            <div class="toolbar">
              <div>当前页 <b>{{ filtered.length }}</b> 项 <span>· 全部 {{assetTotal}} 项</span></div>
              <div><button :class="{ active: density === 'compact' }" @click="density='compact'">紧凑</button><button :class="{ active: density === 'comfortable' }" @click="density='comfortable'">舒适</button><select v-model="assetSort" @change="applyAssetFilters"><option value="created_at">最近更新</option><option value="name">名称</option><option value="size">文件大小</option></select><button @click="assetDirection=assetDirection==='desc'?'asc':'desc';applyAssetFilters()">{{assetDirection==='desc'?'降序':'升序'}}</button></div>
            </div>

            <div v-if="selected.length" class="batch-bar"><b>已选 {{ selected.length }} 项</b><button class="batch-delete" @click="deleteSelectedAssets">删除</button><button @click="openBatchTag('library','remove')">删除标签</button><button @click="openBatchTag('library','add')">添加标签</button><button @click="collectionOpen=true">创建数据集</button><button @click="setPage('relations')">建立关系</button><button @click="exportSelected">导出</button></div>

            <div v-if="demoState === 'loading'" class="state-panel"><div class="spinner"></div><b>正在加载素材</b><p>正在获取筛选结果和预览信息…</p></div>
            <div v-else-if="demoState === 'error'" class="state-panel error-state"><span>!</span><b>素材加载失败</b><p>服务暂时不可用，请检查连接后重试。</p><button @click="demoState='normal'">重新加载</button></div>
            <div v-else-if="demoState === 'forbidden'" class="state-panel"><span>⌾</span><b>没有查看权限</b><p>当前角色不能访问该项目，请联系管理员授权。</p><button @click="setPage('admin')">查看我的角色</button></div>
            <div v-else-if="filtered.length && demoState !== 'empty'" class="asset-grid">
              <article v-for="asset in filtered" :key="asset.id" class="asset-card" :class="{ selected: selected.includes(asset.id) }">
                <button class="asset-preview" :style="{ background: asset.tone }" @click="openAsset(asset)">
                  <img v-if="canDisplayMediaPreview(asset)" :src="asset.preview_url!" :alt="asset.name" />
                  <span v-if="asset.type==='视频' && canDisplayMediaPreview(asset)" class="play-badge">▶</span>
                  <span v-if="!canDisplayMediaPreview(asset)" class="visual-code">{{ asset.type === '图片' ? 'IMG' : asset.type === '视频' ? 'VIDEO' : asset.type === '模型' ? 'MODEL' : 'DATA' }}</span>
                  <small>{{ asset.mark }}</small>
                </button>
                <button class="selector" :aria-label="`选择 ${asset.name}`" @click="toggleSelect(asset.id)">{{ selected.includes(asset.id) ? '✓' : '' }}</button>
                <div class="asset-info"><b :title="asset.name">{{ asset.name }}</b><span v-if="assetTagValues(asset).length"><i v-for="tag in assetTagValues(asset)" :key="String(tag)">{{tag}}</i></span><small>{{ asset.type }} · {{asset.createdAt}} <em v-if="asset.status==='processing'||asset.status==='queued'" class="processing-state">处理中</em><em v-else-if="asset.status==='failed'" class="failed-state">处理失败</em></small></div>
              </article>
            </div>
            <div v-else class="empty"><b>没有匹配的素材</b><p>调整筛选条件或清空搜索词后重试。</p><button @click="query='';resetFilters()">清空筛选</button></div>
            <div v-if="assetFilteredTotal" class="pagination"><span>第 {{assetPage}} / {{assetPages}} 页</span><label>每页 <select v-model="assetPageSize" @change="assetPage=1;loadAssets()"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option><option :value="0">全部</option></select> 项</label><button :disabled="assetPage===1" @click="changeAssetPage(assetPage-1)">‹</button><button :disabled="assetPage===assetPages" @click="changeAssetPage(assetPage+1)">›</button></div>
          </section>
        </div>
      </template>

      <template v-else-if="page === 'relations'">
        <section class="page-head"><div><h1>关联关系</h1></div></section>
        <div class="relation-workflow-tabs"><button :class="{active:relationWorkflow==='auto'}" @click="relationWorkflow='auto'">图片与标注自动关联</button><button :class="{active:relationWorkflow==='model'}" @click="relationWorkflow='model';relationType='trained_on'">模型与素材批量关联</button><button :class="{active:relationWorkflow==='manual'}" @click="relationWorkflow='manual'">其他关系手动建立</button></div>
        <section v-if="relationWorkflow==='auto'" class="auto-relation-guide"><div><h2>创建图片与标注关联关系</h2><p>根据名称相同自动关联的规则去匹配系统内未存在关联关系的图片与标注</p></div><button class="primary" @click="previewAutoRelations">自动关联</button></section>
        <section v-else-if="relationWorkflow==='model'" class="relation-builder">
          <article><span>第 1 步</span><h2>固定一个模型</h2><div class="drop-zone"><b>{{selectedModel?.name||'尚未选择模型'}}</b><small>{{selectedModel?.id||'只展示模型类型素材'}}</small><button @click="openAdvancedRelationPicker('model')">{{selectedModel?'更换模型':'选择模型'}}</button></div></article>
          <div class="relation-arrow"><select v-model="relationType"><option value="trained_on">用于训练</option><option value="produced_by">由训练产生</option><option value="version_of">版本关系</option><option value="contains">属于数据集</option></select><span>→</span></div>
          <article><span>第 2 步</span><h2>批量选择素材</h2><div class="drop-zone target"><b>{{modelTargets.length}} 项素材</b><small>{{modelTargets.slice(0,2).map(item=>item.name).join('、')||'支持图片、视频、标注和数据集素材'}}</small><button @click="openAdvancedRelationPicker('model-target')">{{modelTargets.length?'调整选择':'选择素材'}}</button></div></article>
        </section>
        <section v-else class="relation-builder">
          <article><span>第 1 步</span><h2>选择源资产</h2><div class="drop-zone"><b>{{relationSourceAssets.length}} 项素材</b><small>{{relationSourceAssets.length ? relationSourceAssets.map(item=>item.name).slice(0,2).join('、') : '可选择一项或多项素材'}}</small><button @click="openRelationPicker('source')">{{relationSourceAssets.length?'调整选择':'选择素材'}}</button></div></article>
          <div class="relation-arrow"><select v-model="relationType"><option value="contains">属于数据集</option><option value="annotates">对应标注</option><option value="trained_on">用于训练</option><option value="produced_by">由训练产生</option><option value="version_of">版本关系</option></select><span>→</span></div>
          <article><span>第 2 步</span><h2>选择目标资产</h2><div class="drop-zone target"><b>{{relationTargetName || '尚未选择'}}</b><small>{{relationTargetId || '请选择一项目标素材'}}</small><button @click="openRelationPicker('target')">{{relationTargetId?'重新选择':'选择素材'}}</button></div></article>
        </section>
        <section v-if="relationWorkflow!=='auto'" class="validation"><b>关系预览</b><div><span v-if="relationWorkflow==='model'">{{selectedModel?1:0}} 个模型 → {{modelTargets.length}} 项素材</span><span v-else>{{relationSourceAssets.length}} 项源资产 → {{relationTargetId?1:0}} 项目标资产</span></div><p>提交前将检查重复关系、无效素材和关系方向。</p><button class="primary" @click="relationWorkflow==='model'?previewModelRelations():submitRelations()">预览关系</button></section>
        <section class="relation-history">
          <div class="section-title"><div><h2>历史关联关系</h2></div><label>每页 <select v-model="relationPageSize" @change="relationPage=1;loadRelations()"><option :value="10">10 条</option><option :value="20">20 条</option><option :value="50">50 条</option></select></label></div>
          <div class="relation-history-filters"><input v-model="relationHistoryQuery" placeholder="搜索素材名称或备注" @keyup.enter="relationPage=1;loadRelations()" /><select v-model="relationHistoryType"><option value="">全部关系</option><option v-for="(label,key) in relationTypeLabels" :key="key" :value="key">{{label}}</option></select><select v-model="relationHistoryStatus"><option value="">全部状态</option><option value="active">生效中</option><option value="revoked">已撤销</option></select><input v-model="relationHistoryCreator" placeholder="创建人" /><label>开始时间<input v-model="relationHistoryFrom" type="datetime-local" step="1" /></label><label>结束时间<input v-model="relationHistoryTo" type="datetime-local" step="1" :min="relationHistoryFrom" /></label><button @click="resetRelationHistoryFilters">重置</button><button @click="relationPage=1;loadRelations()">筛选</button></div>
          <div class="relation-table"><div class="relation-row head"><span>源资产</span><span>关系</span><span>目标资产</span><span>创建人</span><span>创建时间</span><span>状态</span><span></span></div><button v-for="item in pagedRelations" :key="item.id" class="relation-row" @click="openRelationDetail(item)"><span><i>{{item.sourceType}}</i><b>{{item.source}}</b></span><strong>{{item.relation}}</strong><span><i>{{item.targetType}}</i><b>{{item.target}}</b></span><span>{{item.operator}}</span><span>{{item.createdAt}}</span><em :class="item.status==='生效中'?'active':'revoked'">{{item.status}}</em><u>详情 ›</u></button></div>
          <div class="pagination"><span>共 {{relationTotal}} 条</span><button :disabled="relationPage===1" @click="relationPage--;loadRelations()">‹</button><button v-for="num in relationPages" :key="num" :class="{active:relationPage===num}" @click="relationPage=num;loadRelations()">{{num}}</button><button :disabled="relationPage===relationPages" @click="relationPage++;loadRelations()">›</button></div>
        </section>
      </template>

      <template v-else-if="page === 'lineage'">
        <section class="page-head"><div><h1>模型溯源</h1></div><div class="primary-actions"><button v-if="lineageRoot" class="secondary" @click="selectedModel=lineageRoot;relationWorkflow='model';relationType='trained_on';setPage('relations')">补充关联</button><button class="primary" @click="openLineagePicker">选择模型</button></div></section>
        <section v-if="lineageLoading" class="state-panel"><div class="spinner"></div><b>正在加载关系图谱</b></section>
        <section v-else-if="lineageRoot" class="lineage-results"><article class="lineage-root"><small>当前模型</small><b>{{lineageRoot.name}}</b><span>{{lineageRoot.media?.extension||lineageRoot.mime_type||'格式未知'}} · {{lineageRoot.tags?.model_version||'未设置版本'}} · {{lineageRoot.updated_at?new Date(lineageRoot.updated_at).toLocaleString('zh-CN'):'时间未知'}}</span></article><div class="lineage-toolbar"><div><button :class="{active:lineageView==='graph'}" @click="lineageView='graph'">关系图</button><button :class="{active:lineageView==='list'}" @click="lineageView='list'">分组列表</button></div><select v-model="lineageTypeFilter"><option value="">全部类型</option><option value="image">图片</option><option value="video">视频</option><option value="annotation">标注</option><option value="model">模型</option><option value="snapshot">数据集</option></select><select v-model="lineageRelationFilter"><option value="">全部关系</option><option v-for="(label,key) in relationTypeLabels" :key="key" :value="key">{{label}}</option></select></div><div v-if="filteredLineageEdges.length&&lineageView==='graph'" class="lineage-graph"><button v-for="edge in filteredLineageEdges" :key="edge.id" @click="openRelationDetail(edge)"><span><i>{{edge.sourceType}}</i><b>{{edge.source}}</b></span><strong>{{edge.relation}} →</strong><span><i>{{edge.targetType}}</i><b>{{edge.target}}</b></span></button></div><div v-else-if="filteredLineageEdges.length" class="lineage-groups"><section v-for="group in lineageGroups" :key="String(group[0])"><h3>{{assetTypeLabels[String(group[0])]||String(group[0])}} · {{group[1].length}}</h3><button v-for="edge in group[1]" :key="edge.id" @click="openRelationDetail(edge)"><b>{{edge.relation}}</b><span>{{edge.source}} → {{edge.target}}</span></button></section></div><div v-else class="empty"><b>暂无关联关系</b><p>可以在当前页面补充模型与素材之间的关联。</p></div><small>图谱节点 {{lineageNodes.length}} 个，当前显示关系 {{filteredLineageEdges.length}} 条</small></section>
        <section v-else class="empty"><b>尚未选择模型</b><p>选择一个模型资产后查看完整溯源关系。</p><button @click="openLineagePicker">选择模型</button></section>
      </template>

      <template v-else-if="page === 'downloads'">
        <section class="page-head"><div><h1>下载中心</h1></div><span>共 {{jobTotal}} 个任务</span></section>
        <section v-if="jobRows.length" class="data-table download-table"><div class="table-row head"><span>任务</span><span>任务创建时间</span><span>内容</span><span>进度</span><span>类型</span><span>状态</span><span>操作</span></div><div v-for="job in jobRows" :key="job.id" class="table-row"><b>{{job.name || jobTypeText(job.type)}}</b><span>{{job.created_at ? new Date(job.created_at).toLocaleString('zh-CN') : '时间未知'}}</span><span>{{job.input?.asset_ids?.length ?? 0}} 项</span><span class="progress"><i :style="{width:`${job.progress}%`}"></i><small>{{job.progress}}%</small></span><span>{{jobTypeText(job.type)}}</span><span :class="job.state==='failed'?'failed':job.state==='succeeded'?'done':''">{{jobStateText(job.state)}}</span><button v-if="job.state==='succeeded'&&job.type==='export'" class="primary" @click="downloadExport(job.id)">下载</button><button v-else-if="job.state==='failed'" @click="retryJob(job.id)">重试</button><button v-else disabled>{{job.state==='running'?'处理中':'等待'}}</button></div></section>
        <section v-else class="empty"><b>暂无下载任务</b><p>在素材库选择素材后，点击“导出”创建打包任务。</p><button @click="setPage('library')">返回素材库</button></section>
      </template>

      <template v-else-if="page === 'trash'">
        <section class="page-head">
          <div><h1>回收站</h1></div>
          <div class="primary-actions"><button v-if="trashSelected.length" class="secondary" @click="trashSelected=[]">× 取消选择</button><button class="secondary" :disabled="!trashAssets.length || allTrashSelected" @click="selectTrashPage">✓ 全选</button><button class="secondary" :disabled="!trashAssets.length" @click="invertTrashPage">⇄ 反选</button><button class="secondary danger" :disabled="!trashTotal" @click="emptyTrash">清空回收站</button><button class="primary" :disabled="!trashSelected.length" @click="restoreTrashAssets">还原</button></div>
        </section>
        <section class="trash-shell content-panel">
          <div class="toolbar"><div>当前页 <b>{{trashAssets.length}}</b> 项 <span>· 全部 {{trashTotal}} 项</span></div></div>
          <div v-if="trashSelected.length" class="batch-bar"><b>已选 {{trashSelected.length}} 项</b><button @click="restoreTrashAssets">还原</button></div>
          <div v-if="trashAssets.length" class="asset-grid"><article v-for="asset in trashAssets" :key="asset.id" class="asset-card" :class="{selected:trashSelected.includes(asset.id)}"><div class="asset-preview" :style="{background:asset.tone}"><img v-if="canDisplayMediaPreview(asset)" :src="asset.preview_url!" :alt="asset.name" /><span v-if="asset.type==='视频' && canDisplayMediaPreview(asset)" class="play-badge">▶</span><span v-if="!canDisplayMediaPreview(asset)" class="visual-code">{{asset.type==='图片'?'IMG':asset.type==='视频'?'VIDEO':asset.type==='模型'?'MODEL':'DATA'}}</span><small>{{asset.mark}}</small></div><button class="selector" :aria-label="`选择 ${asset.name}`" @click="toggleTrashSelect(asset.id)">{{trashSelected.includes(asset.id)?'✓':''}}</button><div class="asset-info"><b :title="asset.name">{{asset.name}}</b><small>{{asset.type}} · 删除于 {{asset.createdAt}}</small></div></article></div>
          <div v-else class="empty"><b>回收站为空</b><p>从素材库删除的素材会显示在这里。</p></div>
          <div v-if="trashTotal" class="pagination"><span>第 {{trashPage}} / {{trashPages}} 页</span><label>每页 <select v-model="trashPageSize" @change="trashPage=1;loadTrash()"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option><option :value="0">全部</option></select> 项</label><button :disabled="trashPage===1" @click="trashPage--;loadTrash()">‹</button><button :disabled="trashPage===trashPages" @click="trashPage++;loadTrash()">›</button></div>
        </section>
      </template>

      <template v-else-if="page === 'tags'">
        <section class="page-head"><div><h1>标签管理</h1></div><button class="primary" @click="openNewTag">＋ 新建标签字段</button></section>
        <section class="tag-admin"><article v-for="tag in tagRows" :key="tag.key"><div><span class="tag-dot" :style="{background:tag.color}"></span><b>{{tag.name}}</b><code>{{tag.key}}</code></div><p>{{(tag.values || []).join(' / ') || '允许自由输入'}}</p><div class="tag-actions"><button @click="openEditTag(tag)">修改</button><button @click="removeTag(tag.key,tag.name)">删除</button></div></article></section>
      </template>

      <template v-else-if="page === 'formats'">
        <section class="page-head"><div><h1>格式管理</h1></div><button class="primary" @click="openNewFormat">＋ 新增格式</button></section>
        <section class="tag-admin"><article v-for="row in formatRows" :key="row.asset_type"><div><b>{{assetTypeLabels[row.asset_type] || row.asset_type}}</b><code>{{row.remark || '暂无备注'}}</code></div><p>{{(row.extensions || []).join(' / ') || '暂无文件格式'}}</p><div v-if="!row.built_in" class="tag-actions"><button @click="openEditFormat(row)">修改</button><button @click="removeFormat(row)">删除</button></div></article></section>
      </template>

      <template v-else>
        <section class="page-head"><div><h1>用户管理</h1></div><button class="primary" @click="openNewUser">＋ 新增用户</button></section>
        <section v-if="userRows.length" class="data-table admin-users"><div class="table-row head"><span>用户名</span><span>角色</span><span>状态</span><span>操作</span></div><div v-for="user in userRows" :key="user.id" class="table-row"><b>{{user.username}}</b><span>{{user.roles.map(roleText).join('、')}}</span><span>{{userStatusText(user.status)}}</span><span class="user-actions"><template v-if="user.username!=='admin'"><button @click="openEditUser(user)">编辑</button><button class="danger-inline" @click="removeUser(user)">删除</button></template><span v-else>—</span></span></div></section>
      </template>
    </main>

    <aside v-if="activeAsset" class="detail-sheet" :class="{'is-scrolling':detailSheetScrolling}" @scroll.passive="showDetailScrollbar">
      <button class="close" @click="mediaViewerOpen=false;detailId=null;detailAsset=null">×</button>
      <button v-if="activeAsset.type==='图片'||activeAsset.type==='视频'" class="media-nav previous" :disabled="!hasPreviousMedia" aria-label="上一个图片或视频" @click="openAdjacentMedia(-1)">‹</button>
      <button v-if="activeAsset.type==='图片'||activeAsset.type==='视频'" class="media-nav next" :disabled="!hasNextMedia" aria-label="下一个图片或视频" @click="openAdjacentMedia(1)">›</button>
      <div class="detail-preview annotation-preview" :class="{'media-detail':activeAsset.type==='图片'||activeAsset.type==='视频'}" :style="[{background:activeAsset.tone},detailMediaStyle]"><img v-if="activeAsset.type==='图片' && (activeAsset.download_url||activeAsset.preview_url)" :src="activeAsset.download_url||activeAsset.preview_url" :alt="activeAsset.name" title="点击查看原图" @click="openMediaViewer" /><video v-else-if="activeAsset.type==='视频' && activeAsset.download_url" :src="activeAsset.download_url" :poster="activeAsset.preview_url" preload="metadata" title="点击查看原视频" @click="openMediaViewer">当前浏览器不支持播放此视频</video><svg v-if="activeAsset.type==='图片' && activeAnnotationSource?.items?.length" class="annotation-layer" viewBox="0 0 100 100" preserveAspectRatio="none"><g v-for="item in activeAnnotationSource.items" :key="item.id"><polygon v-for="(polygon,index) in item.polygons || []" :key="`${item.id}-${index}`" :points="polygonPoints(polygon)" :fill="annotationColor(item.label)" fill-opacity=".18" :stroke="annotationColor(item.label)" vector-effect="non-scaling-stroke" /><rect :x="item.bbox.x*100" :y="item.bbox.y*100" :width="item.bbox.width*100" :height="item.bbox.height*100" fill="none" :stroke="annotationColor(item.label)" vector-effect="non-scaling-stroke" /><text :x="item.bbox.x*100" :y="Math.max(3,item.bbox.y*100)" :fill="annotationColor(item.label)" vector-effect="non-scaling-stroke">{{item.label}}{{item.confidence!=null?` ${(item.confidence*100).toFixed(0)}%`:''}}</text></g></svg><b v-if="activeAsset.type!=='图片'&&activeAsset.type!=='视频'">{{activeAsset.type}}</b><span>{{activeAsset.mark}}</span></div>
      <section v-if="activeAsset.type==='图片'" class="annotation-source-panel"><div><b>标注预览</b><small v-if="annotationLoading">正在读取关联标注…</small><small v-else-if="!annotationSources.length">尚未建立图片与标注的对应关系</small><small v-else-if="activeAnnotationSource?.error">{{activeAnnotationSource.error}}</small><small v-else-if="activeAnnotationSource && !activeAnnotationSource.matched">关联标注中未找到当前图片</small><small v-else-if="!activeAnnotationSource?.items?.length">尚未建立图片与标注的对应关系</small><small v-else>{{activeAnnotationSource?.format}} · {{activeAnnotationSource.items.length}} 个标注<span v-if="activeAnnotationSource?.ignored_shapes"> · 已忽略 {{activeAnnotationSource.ignored_shapes}} 个未支持形状</span></small></div><select v-if="annotationSources.length" v-model="selectedAnnotationSourceId"><option v-for="source in annotationSources" :key="source.annotation_asset_id" :value="source.annotation_asset_id">{{source.annotation_name}} · {{source.format || '待识别'}}</option></select></section>
      <h2>{{ activeAsset.name }}</h2>
      <div v-if="assetTagEntries(activeAsset).length" class="detail-tags"><span v-for="tag in assetTagEntries(activeAsset)" :key="`${tag.key}-${tag.value}`" :title="tag.label"><i>{{tag.value}}</i><button :aria-label="`删除标签 ${tag.label} ${tag.value}`" title="删除标签" @click="removeAssetTag(tag.key,tag.value)">×</button></span></div>
      <section class="asset-remark"><label>备注<textarea v-model="remarkDraft" rows="3" maxlength="1000" placeholder="请输入素材备注"></textarea></label><button class="secondary" :disabled="remarkSaving" @click="saveAssetRemark">{{remarkSaving?'保存中…':'保存备注'}}</button></section>
      <dl><dt>资产 ID</dt><dd>{{activeAsset.id}}</dd><dt>校验值</dt><dd>{{activeAsset.sha256 || '计算中'}}</dd><dt>对象大小</dt><dd>{{activeAsset.size ? `${(activeAsset.size/1024/1024).toFixed(2)} MB` : '未知'}}</dd><dt>处理状态</dt><dd :class="{failed:activeAsset.status==='failed'}">{{processingStatusText(activeAsset.status)}}</dd><dt>创建时间</dt><dd>{{activeAsset.createdAt}}</dd><dt>修改时间</dt><dd>{{activeAsset.updatedAt || activeAsset.createdAt}}</dd><template v-if="activeAsset.processing_error?.message"><dt>失败原因</dt><dd class="failed">{{activeAsset.processing_error.message}}</dd></template></dl>
      <div class="relation-mini"><b>关联关系</b><p>当前有效关系 <span>{{activeAsset.relations?.length || 0}}</span></p></div>
      <div v-if="activeAsset.type==='模型'||activeAsset.download_url" class="detail-actions">
        <button v-if="activeAsset.type==='模型'" class="secondary full" @click="openLineage(activeAsset)">查看模型溯源</button>
        <a v-if="activeAsset.download_url" class="primary full button-link" :href="activeAsset.download_url" :download="activeAsset.name">下载原文件</a>
      </div>
    </aside>

    <aside v-if="activeRelation" class="detail-sheet relation-detail" :class="{'is-scrolling':detailSheetScrolling}" @scroll.passive="showDetailScrollbar">
      <button class="close" @click="relationDetailId=null;relationDetailData=null">×</button>
      <h2>{{activeRelation.relation}}</h2>
      <div class="relation-route"><div><button v-if="activeRelation.sourceAsset&&['image','video'].includes(activeRelation.sourceAsset.type)" class="relation-media-thumb" @click="openRelationMedia(activeRelation.sourceAsset)"><img v-if="activeRelation.sourceAsset.preview_url" :src="activeRelation.sourceAsset.preview_url" :alt="activeRelation.source" /><span v-else>{{activeRelation.sourceType}}</span></button><small>源资产 · {{activeRelation.sourceType}}</small><b :title="activeRelation.source">{{activeRelation.source}}</b></div><span>→</span><div><button v-if="activeRelation.targetAsset&&['image','video'].includes(activeRelation.targetAsset.type)" class="relation-media-thumb" @click="openRelationMedia(activeRelation.targetAsset)"><img v-if="activeRelation.targetAsset.preview_url" :src="activeRelation.targetAsset.preview_url" :alt="activeRelation.target" /><span v-else>{{activeRelation.targetType}}</span></button><small>目标资产 · {{activeRelation.targetType}}</small><b :title="activeRelation.target">{{activeRelation.target}}</b></div></div>
      <dl><dt>当前状态</dt><dd><span :class="activeRelation.status==='生效中'?'ok':'failed'">{{activeRelation.status}}</span></dd><dt>创建人</dt><dd>{{activeRelation.operator}}</dd><dt>创建时间</dt><dd>{{activeRelation.createdAt}}</dd><dt>来源</dt><dd>{{activeRelation.origin}}</dd><template v-if="activeRelation.status==='已撤销'"><dt>撤销原因</dt><dd>{{activeRelation.revokeReason || '未填写'}}</dd></template></dl>
      <section v-if="activeRelation.status==='生效中'" class="revoke-preview"><b>撤销关联关系</b><textarea v-model="revokeReason" placeholder="撤销原因（选填）" rows="3"></textarea><button @click="revokeActiveRelation">确认撤销关系</button></section>
    </aside>

    <div v-if="toast" class="toast" :class="`toast-${toastKind}`"><template v-if="toastKind==='success'">✓ </template>{{ toast }}</div>
    <div v-if="showLogin" class="login-stage">
      <button class="login-close" aria-label="关闭登录预览" @click="showLogin=false">×</button>
      <section class="login-card">
        <div class="login-brand"><span class="brand-mark">VA</span><b>视觉资产库</b></div>
        <h1>登录后继续归档工作</h1><p>使用管理员分配的团队账户访问素材、数据集和模型。</p>
        <label>用户名<input v-model="loginUsername" autocomplete="username" @keyup.enter="login" /></label><label>密码<input v-model="loginPassword" type="password" autocomplete="current-password" @keyup.enter="login" /></label>
        <div class="login-option"><label><input type="checkbox" checked /> 保持登录</label></div>
        <p v-if="loginError" class="form-error">{{loginError}}</p>
        <button class="primary full" :disabled="loginBusy" @click="login">{{loginBusy?'正在登录…':'登录'}}</button>
      </section>
    </div>

    <div v-if="uploadOpen" class="modal-stage">
      <section class="upload-dialog">
        <button class="close" @click="uploadOpen=false">×</button><h2>上传素材</h2><p>单文件默认上限 10 GB；压缩包默认作为压缩文件保存，手动选择“图片+标注”后才会按 CVAT 数据集包解析。</p>
        <label class="file-select-button"><input type="file" multiple @change="chooseFile" /><span>点击选择文件</span></label>
        <div v-if="uploadFiles.length" class="selected-files"><article v-for="file in uploadFiles" :key="uploadFileKey(file)" class="selected-file"><div><b>{{file.name}}</b><small>{{(file.size/1024/1024).toFixed(1)}} MB · {{uploadTypeStatus(file)}}</small></div><select v-model="uploadTypeOverrides[uploadFileKey(file)]" aria-label="选择资产类型"><option value="" disabled>选择类型</option><option value="image">图片</option><option value="video">视频</option><option value="annotation">标注</option><option value="model">模型</option><option value="archive">压缩文件</option><option value="image_annotation">图片+标注</option><option value="other">其他</option></select><button type="button" aria-label="移除文件" title="移除" :disabled="uploadBusy" @click="removeUploadFile(file)">×</button></article></div>
        <div v-if="uploadFiles.length" class="upload-tag-tools"><button class="secondary" type="button" @click="openBatchTag('upload')">＋ 添加标签</button><div v-if="uploadTagEntries.length" class="upload-tag-list"><span v-for="tag in uploadTagEntries" :key="`${tag.key}-${tag.value}`"><b>{{tag.label}}</b>：{{tag.value}}<button type="button" :aria-label="`删除${tag.label}标签${tag.value}`" @click="removeUploadTag(tag.key,tag.value)">×</button></span></div></div>
        <div v-if="uploadBusy" class="upload-meter"><i :style="{width:`${uploadProgress}%`}"></i></div><p v-if="uploadError" class="form-error">{{uploadError}}</p>
        <div class="dialog-actions"><button class="secondary" @click="uploadOpen=false">取消</button><button class="primary" :disabled="uploadBusy" @click="uploadAsset">{{uploadBusy?'正在上传…':'开始上传'}}</button></div>
      </section>
    </div>
    <div v-if="batchTagOpen" class="modal-stage">
      <section class="upload-dialog compact-dialog"><button class="close" @click="batchTagOpen=false">×</button><h2>为 {{batchTagTarget==='upload'?uploadFiles.length:selected.length}} 项素材{{batchTagAction==='add'?'添加':'删除'}}标签</h2><div class="upload-fields"><label>标签<select v-model="batchTagKey" @change="batchTagValue='' "><option v-for="tag in tagDefinitions" :key="tag.key" :value="tag.key">{{tag.label}}</option></select></label><label>标签值<select v-if="selectedTagDefinition(batchTagKey)?.values?.length && !selectedTagDefinition(batchTagKey)?.free_input" v-model="batchTagValue"><option value="" disabled>请选择</option><option v-for="value in selectedTagDefinition(batchTagKey)?.values" :key="value" :value="value">{{value}}</option></select><input v-else v-model="batchTagValue" placeholder="请输入标签值" /></label></div><div class="dialog-actions"><button class="secondary" @click="batchTagOpen=false">取消</button><button class="primary" @click="applyBatchTag">{{batchTagAction==='add'?'添加标签':'删除标签'}}</button></div></section>
    </div>
    <div v-if="collectionOpen" class="modal-stage"><section class="upload-dialog compact-dialog"><button class="close" @click="collectionOpen=false">×</button><h2>用 {{selected.length}} 项素材创建数据集</h2><div class="form-stack"><label>名称<input v-model="collectionName" placeholder="例如 helmet_train_v1" /></label><label>说明<textarea v-model="collectionDescription" rows="3" /></label><label class="inline-check"><input v-model="collectionFreeze" type="checkbox" /> 创建后冻结，作为不可变训练集快照</label></div><div class="dialog-actions"><button class="secondary" @click="collectionOpen=false">取消</button><button class="primary" @click="createCollection">创建数据集</button></div></section></div>
    <div v-if="savedViewOpen" class="modal-stage"><section class="upload-dialog compact-dialog"><button class="close" @click="savedViewOpen=false">×</button><h2>{{editingViewId?'修改视图名称':'保存视图'}}</h2><div class="form-stack"><label>请输入视图名称<input v-model="savedViewName" autofocus @keyup.enter="saveCurrentView" /></label></div><div class="dialog-actions"><button class="secondary" @click="savedViewOpen=false">取消</button><button class="primary" @click="saveCurrentView">{{editingViewId?'保存修改':'保存视图'}}</button></div></section></div>
    <div v-if="tagOpen" class="modal-stage"><section class="upload-dialog compact-dialog tag-dialog"><button class="close" @click="tagOpen=false">×</button><h2>{{editingTagKey?'修改标签字段':'新建标签字段'}}</h2><div class="form-stack"><label>标签名称<input v-model="newTag.name" placeholder="例如 天气" /></label><label>备注<input v-model="newTag.key" :disabled="Boolean(editingTagKey)" placeholder="例如 weather" /></label><div class="tag-values-editor"><div class="field-label"><span>标签值</span><button class="add-value" type="button" @click="addTagValue">＋ 新增</button></div><p v-if="!tagValueRows.length" class="value-empty">暂无标签值，点击“新增”添加</p><div v-for="row in tagValueRows" :key="row.id" class="tag-value-row"><input v-model="row.value" :disabled="!row.editing" placeholder="请输入标签值" @keyup.enter="row.editing=false" /><button type="button" @click="toggleTagValueEdit(row)">{{row.editing?'完成':'修改'}}</button><button class="remove-value" type="button" @click="removeTagValue(row.id)">删除</button></div></div><label class="color-field">颜色<div class="color-control"><label class="color-picker-button" title="点击选择颜色"><span class="color-swatch large" :style="{background:newTag.color}"></span><span>选择颜色</span><input v-model="tagPickerColor" type="color" aria-label="选择颜色" @change="applyPickerColor" /></label><input v-model="newTag.color" class="color-code" aria-label="颜色值" maxlength="7" placeholder="#64748B" /></div></label><label class="inline-check"><input v-model="newTag.free_input" type="checkbox" /> 允许输入枚举以外的值</label></div><div class="dialog-actions"><button class="secondary" @click="tagOpen=false">取消</button><button class="primary" @click="createTag">保存标签</button></div></section></div>
    <div v-if="confirmOpen" class="modal-stage confirm-stage"><section class="upload-dialog compact-dialog confirm-dialog"><h2>{{confirmTitle}}</h2><p>{{confirmMessage}}</p><div class="dialog-actions"><button class="secondary" :disabled="confirmBusy" @click="cancelConfirmation">取消</button><button class="confirm-delete" :disabled="confirmBusy" @click="runConfirmedAction">{{confirmBusy?'正在处理…':confirmActionText}}</button></div></section></div>
    <div v-if="userOpen" class="modal-stage"><section class="upload-dialog compact-dialog"><button class="close" @click="userOpen=false">×</button><h2>{{editingUserId?'编辑用户':'新增用户'}}</h2><div class="form-stack"><label>用户名<input v-model="newUser.username" autocomplete="off" placeholder="至少 3 个字符" /></label><label>{{editingUserId?'新密码（留空则不修改）':'初始密码'}}<input v-model="newUser.password" type="password" autocomplete="new-password" placeholder="至少 8 个字符" /></label><label>角色<select v-model="newUser.role"><option value="admin">管理员</option><option value="data_manager">数据管理员</option><option value="annotator">标注员</option><option value="ml_engineer">算法工程师</option><option value="viewer">只读访客</option></select></label><label v-if="editingUserId">账号状态<select v-model="newUser.status"><option value="active">正常</option><option value="disabled">已停用</option></select></label></div><div class="dialog-actions"><button class="secondary" @click="userOpen=false">取消</button><button class="primary" @click="createUser">{{editingUserId?'保存修改':'创建用户'}}</button></div></section></div>
    <div v-if="mediaViewerOpen && viewerAsset" class="media-viewer" @click.self="closeMediaViewer"><div class="media-viewer-tools"><button aria-label="缩小" title="缩小" :disabled="mediaViewerZoom<=.25" @click="changeMediaViewerZoom(-.25)">−</button><b>{{Math.round(mediaViewerZoom*100)}}%</b><button aria-label="放大" title="放大" :disabled="mediaViewerZoom>=4" @click="changeMediaViewerZoom(.25)">＋</button><button v-if="viewerAsset.type==='图片' && !pickerPreviewAsset" class="annotation-toggle" :class="{active:mediaViewerAnnotations}" @click="mediaViewerAnnotations=!mediaViewerAnnotations">{{mediaViewerAnnotations?'隐藏标注':'显示标注'}}</button></div><button class="media-viewer-close" aria-label="关闭大图" @click="closeMediaViewer">×</button><div class="media-viewer-scroll"><div v-if="viewerAsset.type==='图片'" class="original-media" :style="originalMediaStyle"><img :src="viewerAsset.download_url||viewerAsset.preview_url" :alt="viewerAsset.name" /><svg v-if="!pickerPreviewAsset && mediaViewerAnnotations && activeAnnotationSource?.items?.length" class="annotation-layer" viewBox="0 0 100 100" preserveAspectRatio="none"><g v-for="item in activeAnnotationSource.items" :key="item.id"><polygon v-for="(polygon,index) in item.polygons || []" :key="`${item.id}-${index}`" :points="polygonPoints(polygon)" :fill="annotationColor(item.label)" fill-opacity=".18" :stroke="annotationColor(item.label)" vector-effect="non-scaling-stroke" /><rect :x="item.bbox.x*100" :y="item.bbox.y*100" :width="item.bbox.width*100" :height="item.bbox.height*100" fill="none" :stroke="annotationColor(item.label)" vector-effect="non-scaling-stroke" /><text :x="item.bbox.x*100" :y="Math.max(3,item.bbox.y*100)" :fill="annotationColor(item.label)" vector-effect="non-scaling-stroke">{{item.label}}</text></g></svg></div><video v-else :src="viewerAsset.download_url" :poster="viewerAsset.preview_url" :style="originalMediaStyle" controls autoplay>当前浏览器不支持播放此视频</video></div></div>
    <div v-if="formatOpen" class="modal-stage"><section class="upload-dialog compact-dialog tag-dialog"><button class="close" @click="formatOpen=false">×</button><h2>{{editingFormatType?'修改格式':'新增格式'}}</h2><div class="form-stack"><label>素材类型<select v-if="!editingFormatType" v-model="newFormatType"><option v-for="type in availableFormatTypes" :key="type" :value="type">{{assetTypeLabels[type]}}</option></select><input v-else :value="assetTypeLabels[editingFormatType]" disabled /></label><label>备注<input v-model="formatRemark" placeholder="请输入备注" /></label><div class="tag-values-editor"><div class="field-label"><span>文件格式</span><button class="add-value" type="button" @click="addFormatValue">＋ 新增</button></div><p v-if="!formatValueRows.length" class="value-empty">暂无文件格式，点击“新增”添加</p><div v-for="row in formatValueRows" :key="row.id" class="tag-value-row"><input v-model="row.value" :disabled="row.protected || !row.editing" placeholder="例如 .jpg" @keyup.enter="row.editing=false" /><template v-if="!row.protected"><button type="button" @click="toggleFormatValueEdit(row)">{{row.editing?'完成':'修改'}}</button><button class="remove-value" type="button" @click="removeFormatValue(row.id)">删除</button></template></div></div></div><div class="dialog-actions"><button class="secondary" @click="formatOpen=false">取消</button><button class="primary" @click="saveFormat">保存格式</button></div></section></div>
    <div v-if="relationPickerOpen" class="modal-stage"><section class="upload-dialog relation-picker-dialog"><button class="close" @click="relationPickerOpen=false">×</button><h2>{{relationPickerContext==='auto-image'?'选择图片':relationPickerContext==='auto-annotation'?'选择标注':relationPickerContext==='model'?'选择模型':relationPickerContext==='model-target'?'选择关联素材':relationPickerContext==='source'?'选择源资产':'选择目标资产'}}</h2>
      <div class="relation-picker-layout"><aside class="picker-filters"><label>搜索<input v-model="relationPickerQuery" placeholder="名称或备注" /></label><label v-if="!['auto-image','auto-annotation','model'].includes(relationPickerContext)">资产类型<select v-model="relationPickerType"><option value="">全部类型</option><option value="image">图片</option><option value="video">视频</option><option value="annotation">标注</option><option value="model">模型</option><option value="archive">压缩文件</option><option v-if="['model-target','target'].includes(relationPickerContext)" value="collection">数据集</option></select></label><button v-if="relationPickerType!=='collection'" class="untagged-filter picker-untagged-filter" :class="{active:relationPickerNoTags}" @click="relationPickerNoTags=!relationPickerNoTags">无标签</button><div v-if="relationPickerType!=='collection'" class="advanced-head"><div><b>高级筛选条件</b><small>多个条件可组合</small></div><button @click="addPickerRule">＋ 条件</button></div><div v-if="relationPickerType!=='collection'" class="match-mode"><span>符合</span><button :class="{active:relationPickerMatch==='all'}" @click="relationPickerMatch='all'">全部</button><button :class="{active:relationPickerMatch==='any'}" @click="relationPickerMatch='any'">任一</button></div><div v-if="relationPickerType!=='collection'" class="picker-filter-rules"><div v-for="rule in relationPickerRules" :key="rule.id" class="picker-filter-rule"><select v-model="rule.tag" @change="changeRuleTag(rule)"><option v-for="field in filterDefinitions" :key="field.key" :value="field.key">{{field.label}}</option></select><select v-model="rule.operator" @change="changeRuleOperator(rule)"><template v-if="isTimeFilter(rule.tag)"><option value="equals">等于</option><option value="lt">小于</option><option value="gt">大于</option><option value="between">位于</option></template><template v-else><option value="equals">等于</option><option v-if="rule.tag!=='remark'" value="notEquals">不等于</option><option value="contains">包含</option><option value="notContains">不包含</option></template></select><div v-if="isTimeFilter(rule.tag)" class="filter-time-values" :class="{range:rule.operator==='between'}"><input v-model="rule.value" type="datetime-local" step="1" /><span v-if="rule.operator==='between'">至</span><input v-if="rule.operator==='between'" v-model="rule.valueEnd" type="datetime-local" step="1" :min="nextDateTimeValue(rule.value)" /></div><select v-else-if="selectedFilterDefinition(rule.tag)?.values?.length&&!selectedFilterDefinition(rule.tag)?.free_input" v-model="rule.value"><option value="" disabled>请选择</option><option v-for="value in selectedFilterDefinition(rule.tag)?.values" :key="value" :value="value">{{value}}</option></select><input v-else v-model="rule.value" placeholder="请输入值" /><button class="remove-rule" @click="relationPickerRules=relationPickerRules.filter(item=>item.id!==rule.id)">×</button></div></div><button class="apply-filter" @click="applyPickerFilters">应用筛选</button></aside>
      <div class="picker-results"><div class="picker-selection-tools"><b>已选 {{relationPickerSelection.length}} 项</b><button v-if="relationPickerSelection.length" @click="relationPickerSelection=[]">取消选择</button><button v-if="!['target','model'].includes(relationPickerContext)" @click="selectPickerPage">全选</button><button v-if="!['target','model'].includes(relationPickerContext)" @click="invertPickerPage">反选</button></div><div v-if="relationPickerSelection.length" class="picker-selected-list"><button v-for="item in relationPickerSelection" :key="item.id" @click="togglePickerItem(item)">{{item.name}} ×</button></div><div v-if="relationPickerLoading" class="picker-empty">正在加载…</div><div v-else-if="relationPickerItems.length" class="picker-list relation-picker-table"><div class="picker-list-head"><span>格式</span><span>名称</span><span>备注</span><span>标签</span><span></span></div><button v-for="item in relationPickerItems" :key="item.id" :class="{selected:relationPickerSelectedIds.includes(String(item.id)),self:isPickerItemSelf(item)}" :disabled="isPickerItemSelf(item)" :title="isPickerItemSelf(item)?'不能选择素材自身':''" @click="togglePickerItem(item)"><span class="picker-format" :title="pickerFormat(item)"><img v-if="['image','video'].includes(item.type)&&item.preview_url" :src="item.preview_url" :alt="item.name" title="点击查看原分辨率文件" @click.stop="openPickerMedia(item)" /><em>{{pickerFormat(item)}}</em></span><b :title="item.name">{{item.name}}</b><small :title="item.remark||'—'">{{item.remark||'—'}}</small><small :title="pickerTagsText(item)">{{pickerTagsText(item)}}</small><i>{{isPickerItemSelf(item)?'不可选':relationPickerSelectedIds.includes(String(item.id))?'✓':'○'}}</i></button></div><div v-else class="picker-empty">没有匹配的素材</div><div class="picker-pagination"><span>共 {{relationPickerTotal}} 项</span><label>每页 <select v-model="relationPickerPageSize" @change="relationPickerPage=1;loadRelationPicker()"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option><option :value="0">全部</option></select></label><button :disabled="relationPickerPage===1" @click="relationPickerPage--;loadRelationPicker()">‹</button><b>第 {{relationPickerPage}} / {{relationPickerPages}} 页</b><button :disabled="relationPickerPage===relationPickerPages" @click="relationPickerPage++;loadRelationPicker()">›</button></div></div></div><div class="dialog-actions"><button class="secondary" @click="relationPickerOpen=false">取消</button><button class="primary" @click="storePickerSelection">完成选择</button></div></section></div>
    <div v-if="relationPreviewOpen" class="modal-stage"><section class="upload-dialog relation-preview-dialog"><button class="close" @click="relationPreviewOpen=false">×</button><h2>{{relationPreviewKind==='auto'?'自动关联结果':'关系预览'}}</h2><p v-if="relationPreviewKind==='auto'" class="auto-match-result">本次共匹配成功 <b>{{relationPreview?.counts?.ready||0}}</b> 组图片与标注，请确认是否建立关联关系。</p><div class="preview-summary"><article class="ready"><b>{{relationPreview?.counts?.ready||0}}</b><span>{{relationPreviewKind==='auto'?'匹配成功':'可以建立'}}</span></article><article><b>{{relationPreview?.counts?.existing||0}}</b><span>已存在</span></article><article v-if="relationPreviewKind==='auto'" class="warn"><b>{{(relationPreview?.counts?.image_conflicts||0)+(relationPreview?.counts?.annotation_conflicts||0)}}</b><span>重名冲突</span></article><article class="warn"><b>{{relationPreviewKind==='auto'?(relationPreview?.counts?.unmatched_images||0)+(relationPreview?.counts?.unmatched_annotations||0):relationPreview?.counts?.invalid||0}}</b><span>{{relationPreviewKind==='auto'?'未匹配':'无效关系'}}</span></article></div><div class="preview-groups"><section v-if="relationPreview?.ready?.length"><h3>{{relationPreviewKind==='auto'?'匹配成功':'可以建立'}}</h3><p v-for="item in relationPreview.ready.slice(0,100)" :key="item.relation?.source_id||item.source.id">{{item.source.name}} → {{item.target.name}}</p></section><section v-if="relationPreview?.existing?.length"><h3>已存在</h3><p v-for="item in relationPreview.existing.slice(0,100)" :key="item.existing_relation_id||item.source.id">{{item.source.name}} → {{item.target.name}}</p></section><section v-if="relationPreviewKind==='auto'&&relationPreview?.image_conflicts?.length"><h3>图片重名</h3><p v-for="item in relationPreview.image_conflicts" :key="item.stem">{{item.stem}}（{{item.items.length}} 项）</p></section><section v-if="relationPreviewKind==='auto'&&relationPreview?.annotation_conflicts?.length"><h3>标注重名</h3><p v-for="item in relationPreview.annotation_conflicts" :key="item.stem">{{item.stem}}（{{item.items.length}} 项）</p></section><section v-if="relationPreviewKind==='auto'&&relationPreview?.unmatched_images?.length"><h3>未匹配图片</h3><p v-for="item in relationPreview.unmatched_images" :key="item.id">{{item.name}}</p></section><section v-if="relationPreviewKind==='auto'&&relationPreview?.unmatched_annotations?.length"><h3>未匹配标注</h3><p v-for="item in relationPreview.unmatched_annotations" :key="item.id">{{item.name}}</p></section><section v-if="relationPreview?.invalid?.length"><h3>无效或已删除</h3><p v-for="(item,index) in relationPreview.invalid" :key="item.id||index">{{item.source?.name||item.id||item.relation?.source_id}}：{{item.message}}</p></section></div><div class="dialog-actions"><button class="secondary" @click="relationPreviewOpen=false">{{relationPreviewKind==='auto'?'取消':'返回调整'}}</button><button class="primary" :disabled="!relationPreview?.ready?.length||relationSubmitting" @click="confirmRelationPreview">{{relationSubmitting?'正在提交…':relationPreviewKind==='auto'?`确认关联 ${relationPreview?.ready?.length||0} 组`:`确认建立 ${relationPreview?.ready?.length||0} 条关系`}}</button></div></section></div>
  </div>
</template>
