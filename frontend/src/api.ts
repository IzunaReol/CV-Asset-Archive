import { parseStoredSession, persistedSession } from './sessionPolicy'
import type { ApiList, AssetStats, DatasetOption, Job, RelationGraph } from './apiTypes'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

type Tokens = { access_token:string; access_expires_at:string; user:Record<string, unknown> }

const SESSION_KEY = 'cv-archive-session'
let rememberSession = Boolean(localStorage.getItem(SESSION_KEY))
let tokens: Tokens | null = parseStoredSession(localStorage.getItem(SESSION_KEY) || sessionStorage.getItem(SESSION_KEY))
let refreshPromise: Promise<boolean> | null = null
let sessionExpiredHandler: (() => void) | null = null
let serviceStatusHandler: ((status:{state:'online'|'degraded'|'offline';message:string;checks?:Record<string,boolean>}) => void) | null = null

if (tokens) {
  const storage = rememberSession ? localStorage : sessionStorage
  storage.setItem(SESSION_KEY, JSON.stringify(persistedSession(tokens)))
} else {
  localStorage.removeItem(SESSION_KEY)
  sessionStorage.removeItem(SESSION_KEY)
}

function saveTokens(next: Tokens | null) {
  tokens = next
  localStorage.removeItem(SESSION_KEY)
  sessionStorage.removeItem(SESSION_KEY)
  if (next) {
    const storage = rememberSession ? localStorage : sessionStorage
    storage.setItem(SESSION_KEY, JSON.stringify(persistedSession(next)))
  }
}

function expireSession() {
  saveTokens(null)
  sessionExpiredHandler?.()
}

async function refreshSession(): Promise<boolean> {
  if (!tokens) return false
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method:'POST',
      credentials:'include',
      headers:{'content-type':'application/json'},
      body:'{}',
    }).then(async (response) => {
      if (!response.ok) {
        expireSession()
        return false
      }
      saveTokens(await response.json())
      return true
    }).catch(() => {
      expireSession()
      return false
    }).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

async function request<T>(path: string, init: RequestInit = {}, retry = true, transientRetry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('content-type')) headers.set('content-type', 'application/json')
  if (tokens?.access_token) headers.set('authorization', `Bearer ${tokens.access_token}`)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials:'include' })
  } catch {
    if ((init.method || 'GET') === 'GET' && transientRetry) {
      await new Promise(resolve => setTimeout(resolve, 800))
      return request<T>(path, init, retry, false)
    }
    serviceStatusHandler?.({state:'offline',message:'无法连接至 API 服务'})
    throw new Error('无法连接至服务器，请重启后端服务')
  }
  if (response.status < 500) serviceStatusHandler?.({state:'online',message:'服务连接正常'})
  if (response.status === 401 && retry && tokens) {
    if (await refreshSession()) return request<T>(path, init, false, transientRetry)
  }
  if (!response.ok) {
    const isJson = response.headers.get('content-type')?.includes('application/json')
    const payload = isJson ? await response.json().catch(() => ({})) : {}
    if ([502,503,504].includes(response.status) && (init.method || 'GET') === 'GET' && transientRetry) {
      await new Promise(resolve => setTimeout(resolve, 800))
      return request<T>(path, init, retry, false)
    }
    if (response.status >= 500) {
      serviceStatusHandler?.({state:'degraded',message:payload?.error?.message || '基础服务暂时不可用',checks:payload?.error?.details})
    }
    if (response.status >= 500 && !isJson) {
      throw new Error('服务器异常，请重启后端服务')
    }
    const validationMessage = Array.isArray(payload?.detail)
      ? payload.detail.map((item:any) => item?.msg).filter(Boolean).join('；')
      : (typeof payload?.detail === 'string' ? payload.detail : '')
    throw new Error(payload?.error?.message || validationMessage || `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

async function download(path:string, filename:string) {
  const headers = new Headers()
  if (tokens?.access_token) headers.set('authorization', `Bearer ${tokens.access_token}`)
  let response = await fetch(`${API_BASE}${path}`, {headers,credentials:'include'})
  if (response.status === 401 && await refreshSession()) {
    headers.set('authorization', `Bearer ${tokens?.access_token || ''}`)
    response = await fetch(`${API_BASE}${path}`, {headers,credentials:'include'})
  }
  if (!response.ok) throw new Error('下载失败')
  const href=URL.createObjectURL(await response.blob())
  const anchor=document.createElement('a');anchor.href=href;anchor.download=filename;anchor.click()
  URL.revokeObjectURL(href)
}

export const api = {
  session: () => tokens,
  onSessionExpired: (handler:() => void) => { sessionExpiredHandler = handler },
  onServiceStatus: (handler:typeof serviceStatusHandler) => { serviceStatusHandler = handler },
  restoreSession: () => tokens?.access_token ? Promise.resolve(true) : refreshSession(),
  login: async (username:string, password:string, remember=true) => {
    rememberSession = remember
    const result = await request<Tokens>('/auth/login', {method:'POST', body:JSON.stringify({username,password,remember})}, false)
    saveTokens(result)
    return result
  },
  logout: async () => {
    if (tokens) await request('/auth/logout', {method:'POST', body:'{}'}).catch(() => undefined)
    saveTokens(null)
  },
  assets: (params:URLSearchParams) => request<{items:any[];total:number;next_cursor?:string|null}>(`/assets?${params}`),
  createAssetSelection: (body:Record<string,unknown>) => request<{selection_id:string;total:number}>('/assets/selection-sets', {method:'POST',body:JSON.stringify(body)}),
  assetStats: () => request<AssetStats>('/assets/stats'),
  asset: (id:string) => request<any>(`/assets/${id}`),
  previewAssetUsage: (body:Record<string,unknown>) => request<any>('/assets/usage-impact', {method:'POST',body:JSON.stringify(body)}),
  assetHistory: (id:string, page=1) => request<any>(`/assets/${id}/history${page>1?`?page=${page}`:''}`),
  updateAssetRemark: (id:string, remark:string) => request<any>(`/assets/${id}/remark`, {method:'PATCH',body:JSON.stringify({remark})}),
  modelParameters: (id:string) => request<{asset_id:string;items:Array<{id:string;name:string;category:string;description:string;value:string|null}>}>(`/assets/${encodeURIComponent(id)}/parameters`),
  updateModelParameters: (id:string, values:Record<string,string|null>) => request<{asset_id:string;items:Array<{id:string;name:string;category:string;description:string;value:string|null}>}>(`/assets/${encodeURIComponent(id)}/parameters`, {method:'PATCH',body:JSON.stringify({values})}),
  annotationOverlays: (id:string) => request<any>(`/assets/${id}/annotation-overlays`),
  archiveAsset: (id:string) => request<any>(`/assets/${id}/archive`, {method:'POST'}),
  initUpload: (body:Record<string, unknown>) => request<any>('/assets/upload-sessions', {method:'POST',body:JSON.stringify(body)}),
  resumableUploads: () => request<any>('/assets/upload-sessions'),
  checkUploadConflicts: (files:Record<string, unknown>[]) => request<any>('/assets/upload-conflicts', {method:'POST',body:JSON.stringify({files})}),
  completeUpload: (body:Record<string, unknown>) => request<any>('/assets/upload-sessions/complete', {method:'POST',body:JSON.stringify(body)}),
  initUploadBatch: (files:Record<string, unknown>[]) => request<any>('/assets/upload-sessions/batch', {method:'POST',body:JSON.stringify({files})}),
  completeUploadBatch: (uploadSessionIds:string[], tags:Record<string,string[]>) => request<any>('/assets/upload-sessions/complete-batch', {method:'POST',body:JSON.stringify({upload_session_ids:uploadSessionIds,tags})}),
  uploadSession: (id:string) => request<any>(`/assets/upload-sessions/${encodeURIComponent(id)}`),
  cancelUploadSession: (id:string) => request<void>(`/assets/upload-sessions/${encodeURIComponent(id)}`, {method:'DELETE'}),
  batchTags: (body:Record<string, unknown>) => request<any>('/assets/batch-tags', {method:'POST',body:JSON.stringify(body)}),
  batchDelete: (body:Record<string,unknown>) => request<any>('/assets/batch-delete', {method:'POST',body:JSON.stringify(body)}),
  trash: (page=1,pageSize=50) => request<any>(`/assets/trash/items?page=${page}&page_size=${pageSize}`),
  restoreTrash: (assetIds:string[]) => request<any>('/assets/trash/restore', {method:'POST',body:JSON.stringify({asset_ids:assetIds})}),
  emptyTrash: () => request<any>('/assets/trash/empty', {method:'POST'}),
  job: (id:string) => request<any>(`/jobs/${id}`),
  relations: (page:number, pageSize:number, filters:Record<string,string>={}) => {
    const params = new URLSearchParams({page:String(page),page_size:String(pageSize),...filters})
    return request<any>(`/relations?${params}`)
  },
  relation: (id:string) => request<any>(`/relations/${id}`),
  relationGraph: (id:string) => request<RelationGraph>(`/relations/graph/${encodeURIComponent(id)}?depth=4&member_limit=500`),
  previewRelations: (body:Record<string, unknown>) => request<any>('/relations/preview', {method:'POST',body:JSON.stringify(body)}),
  previewAnnotationMatches: (body:Record<string, unknown>) => request<any>('/relations/annotation-match-preview', {method:'POST',body:JSON.stringify(body)}),
  createRelations: (body:Record<string, unknown>) => request<any>('/relations/batch', {method:'POST',body:JSON.stringify(body)}),
  revokeRelation: (id:string, reason:string) => request<any>(`/relations/${id}/revoke`, {method:'POST',body:JSON.stringify({reason})}),
  previewRevokeRelation: (id:string) => request<any>(`/relations/${id}/revoke-preview`),
  collections: () => request<any>('/collections'),
  createCollection: (body:Record<string, unknown>) => request<any>('/collections', {method:'POST',body:JSON.stringify(body)}),
  datasets: (params=new URLSearchParams()) => request<any>(`/datasets?${params}`),
  datasetOptions: (page=1, pageSize=50, q='') => request<ApiList<DatasetOption>>(`/datasets/options?page=${page}&page_size=${pageSize}${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  dataset: (id:string) => request<any>(`/datasets/${id}`),
  createDataset: (body:Record<string, unknown>) => request<any>('/datasets', {method:'POST',body:JSON.stringify(body)}),
  updateDataset: (id:string, body:Record<string, unknown>) => request<any>(`/datasets/${id}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteDataset: (id:string) => request<void>(`/datasets/${id}`, {method:'DELETE'}),
  datasetCreators: () => request<any>('/datasets/creators'),
  copyDataset: (id:string, includeAssets:boolean, name:string) => request<any>(`/datasets/${id}/copy`, {method:'POST',body:JSON.stringify({include_assets:includeAssets,name})}),
  datasetTagDistribution: (id:string) => request<any>(`/datasets/${id}/tag-distribution`),
  datasetMembers: (id:string, page=1, pageSize=50, filters=new URLSearchParams()) => request<any>(`/datasets/${id}/members?page=${page}&page_size=${pageSize}&${filters}`),
  datasetMemberStatus: (id:string, assetIds:string[]) => request<{existing_ids:string[]}>(`/datasets/${id}/members/status`, {method:'POST',body:JSON.stringify({asset_ids:assetIds})}),
  addDatasetMembers: (id:string, body:Record<string,unknown>) => request<any>(`/datasets/${id}/members`, {method:'POST',body:JSON.stringify(body)}),
  previewDatasetMembers: (id:string, body:Record<string,unknown>, action:'add'|'remove') => request<any>(`/datasets/${id}/members/preview?action=${action}`, {method:'POST',body:JSON.stringify(body)}),
  removeDatasetMembers: (id:string, body:Record<string,unknown>) => request<any>(`/datasets/${id}/members`, {method:'DELETE',body:JSON.stringify(body)}),
  datasetVersion: (id:string, versionId:string, page=1, pageSize=200) => request<any>(`/datasets/${id}/versions/${versionId}?page=${page}&page_size=${pageSize}`),
  datasetVersions: (id:string) => request<any>(`/datasets/${id}/versions`),
  datasetModels: (id:string) => request<any>(`/datasets/${id}/models`),
  addDatasetModel: (id:string, body:Record<string,unknown>) => request<any>(`/datasets/${id}/models`, {method:'POST',body:JSON.stringify(body)}),
  updateDatasetModelRemark: (id:string, relationId:string, remark:string) => request<any>(`/datasets/${id}/models/${relationId}`, {method:'PATCH',body:JSON.stringify({remark})}),
  removeDatasetModel: (id:string, relationId:string) => request<any>(`/datasets/${id}/models/${relationId}`, {method:'DELETE'}),
  publishDatasetVersion: (id:string, version:string, releaseNote:string) => request<any>(`/datasets/${id}/versions`, {method:'POST',body:JSON.stringify({version,release_note:releaseNote})}),
  compareDatasetVersions: (id:string, fromId:string, toId:string) => request<any>(`/datasets/${id}/compare?from_version_id=${encodeURIComponent(fromId)}&to_version_id=${encodeURIComponent(toId)}`),
  restoreDatasetVersion: (id:string, versionId:string) => request<any>(`/datasets/${id}/restore`, {method:'POST',body:JSON.stringify({version_id:versionId})}),
  exportDataset: (id:string, name?:string) => request<any>(`/datasets/${id}/export`, {method:'POST',body:JSON.stringify({name:name||null})}),
  savedViews: () => request<any>('/saved-views'),
  createSavedView: (body:Record<string, unknown>) => request<any>('/saved-views', {method:'POST',body:JSON.stringify(body)}),
  updateSavedView: (id:string, body:Record<string,unknown>) => request<any>(`/saved-views/${id}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteSavedView: (id:string) => request<void>(`/saved-views/${id}`, {method:'DELETE'}),
  createExport: (body:Record<string, unknown>) => request<any>('/exports', {method:'POST',body:JSON.stringify(body)}),
  jobs: (page=1, pageSize=20, type='', state='', createdFrom='', createdTo='') => request<ApiList<Job>>(`/jobs?page=${page}&page_size=${pageSize}${type ? `&type=${encodeURIComponent(type)}` : ''}${state ? `&state=${encodeURIComponent(state)}` : ''}${createdFrom ? `&created_from=${encodeURIComponent(createdFrom)}` : ''}${createdTo ? `&created_to=${encodeURIComponent(createdTo)}` : ''}`),
  retryJob: (id:string) => request<any>(`/jobs/${id}/retry`, {method:'POST'}),
  cancelJob: (id:string) => request<any>(`/jobs/${id}/cancel`, {method:'POST'}),
  exportDownload: (id:string) => request<any>(`/exports/${id}/download-url`),
  tags: () => request<any>('/tag-definitions'),
  createTag: (body:Record<string, unknown>) => request<any>('/tag-definitions', {method:'POST',body:JSON.stringify(body)}),
  updateTag: (key:string, body:Record<string, unknown>) => request<any>(`/tag-definitions/${encodeURIComponent(key)}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteTag: (key:string) => request<void>(`/tag-definitions/${encodeURIComponent(key)}`, {method:'DELETE'}),
  users: () => request<any>('/users'),
  roles: () => request<any>('/roles'),
  createRoleTemplate: (body:Record<string,unknown>) => request<any>('/role-templates', {method:'POST',body:JSON.stringify(body)}),
  updateRoleTemplate: (id:string, body:Record<string,unknown>) => request<any>(`/role-templates/${id}`, {method:'PUT',body:JSON.stringify(body)}),
  deleteRoleTemplate: (id:string) => request<void>(`/role-templates/${id}`, {method:'DELETE'}),
  previewRoleImpact: (roleRef:string, body:Record<string,unknown>) => request<any>(`/role-impact/${encodeURIComponent(roleRef)}`, {method:'POST',body:JSON.stringify(body)}),
  updateRoleDefinition: (key:string, body:Record<string,unknown>) => request<any>(`/role-definitions/${key}`, {method:'PUT',body:JSON.stringify(body)}),
  deleteRoleDefinition: (key:string) => request<void>(`/role-definitions/${key}`, {method:'DELETE'}),
  myPermissions: () => request<any>('/permissions/me'),
  createUser: (body:Record<string, unknown>) => request<any>('/users', {method:'POST',body:JSON.stringify(body)}),
  updateUser: (id:string, body:Record<string, unknown>) => request<any>(`/users/${id}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteUser: (id:string) => request<void>(`/users/${id}`, {method:'DELETE'}),
  formats: () => request<any>('/format-definitions'),
  createFormat: (body:Record<string, unknown>) => request<any>('/format-definitions', {method:'POST',body:JSON.stringify(body)}),
  updateFormat: (type:string, body:Record<string, unknown>) => request<any>(`/format-definitions/${encodeURIComponent(type)}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteFormat: (type:string) => request<void>(`/format-definitions/${encodeURIComponent(type)}`, {method:'DELETE'}),
  metrics: () => request<{items:Array<{id:string;name:string;category:string;description:string;built_in:boolean}>}>('/metric-definitions'),
  metricCategories: () => request<{items:Array<{id:string;name:string;built_in:boolean}>}>('/metric-categories'),
  createMetricCategory: (name:string) => request<{id:string;name:string;built_in:boolean}>('/metric-categories', {method:'POST',body:JSON.stringify({name})}),
  updateMetricCategory: (id:string, name:string) => request<{id:string;name:string;built_in:boolean}>(`/metric-categories/${encodeURIComponent(id)}`, {method:'PATCH',body:JSON.stringify({name})}),
  deleteMetricCategory: (id:string) => request<void>(`/metric-categories/${encodeURIComponent(id)}`, {method:'DELETE'}),
  createMetric: (body:{name:string;category:string;description:string}) => request<any>('/metric-definitions', {method:'POST',body:JSON.stringify(body)}),
  updateMetric: (id:string, body:{name:string;category:string;description:string}) => request<any>(`/metric-definitions/${encodeURIComponent(id)}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteMetric: (id:string) => request<void>(`/metric-definitions/${encodeURIComponent(id)}`, {method:'DELETE'}),
  auditLogs: (filters:Record<string,string|number>={}) => {
    const params=new URLSearchParams()
    for (const [key,value] of Object.entries(filters)) if (value !== '') params.set(key,String(value))
    return request<any>(`/audit-logs?${params}`)
  },
  exportAuditLogs: (filters:Record<string,string|number>={}) => {
    const params=new URLSearchParams()
    for (const [key,value] of Object.entries(filters)) if (value !== '') params.set(key,String(value))
    return download(`/audit-logs/export?${params}`, `audit-logs-${new Date().toISOString().slice(0,10)}.csv`)
  },
  health: () => request<any>('/system/health', {}, false),
  overview: () => request<any>('/system/overview'),
  projectOverview: (projects:string[]) => {
    const params = new URLSearchParams()
    projects.forEach(project => params.append('projects', project))
    return request<any>(`/projects/overview?${params}`)
  },
  globalSearch: (q:string) => request<any>(`/system/search?q=${encodeURIComponent(q)}`),
}
