import { parseStoredSession, persistedSession } from './sessionPolicy'
import type { ApiList, AssetStats, DatasetOption, Job, RelationGraph } from './apiTypes'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

type Tokens = { access_token:string; access_expires_at:string; user:Record<string, unknown> }

const SESSION_KEY = 'cv-archive-session'
let rememberSession = Boolean(localStorage.getItem(SESSION_KEY))
let tokens: Tokens | null = parseStoredSession(localStorage.getItem(SESSION_KEY) || sessionStorage.getItem(SESSION_KEY))
let refreshPromise: Promise<boolean> | null = null
let sessionExpiredHandler: (() => void) | null = null

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

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('content-type')) headers.set('content-type', 'application/json')
  if (tokens?.access_token) headers.set('authorization', `Bearer ${tokens.access_token}`)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials:'include' })
  } catch {
    throw new Error('无法连接至服务器，请重启后端服务')
  }
  if (response.status === 401 && retry && tokens) {
    if (await refreshSession()) return request<T>(path, init, false)
  }
  if (!response.ok) {
    const isJson = response.headers.get('content-type')?.includes('application/json')
    const payload = isJson ? await response.json().catch(() => ({})) : {}
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

export const api = {
  session: () => tokens,
  onSessionExpired: (handler:() => void) => { sessionExpiredHandler = handler },
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
  updateAssetRemark: (id:string, remark:string) => request<any>(`/assets/${id}/remark`, {method:'PATCH',body:JSON.stringify({remark})}),
  annotationOverlays: (id:string) => request<any>(`/assets/${id}/annotation-overlays`),
  archiveAsset: (id:string) => request<any>(`/assets/${id}/archive`, {method:'POST'}),
  initUpload: (body:Record<string, unknown>) => request<any>('/assets/upload-sessions', {method:'POST',body:JSON.stringify(body)}),
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
  datasetOptions: (q='') => request<ApiList<DatasetOption>>(`/datasets/options?page=1&page_size=200${q ? `&q=${encodeURIComponent(q)}` : ''}`),
  dataset: (id:string) => request<any>(`/datasets/${id}`),
  createDataset: (body:Record<string, unknown>) => request<any>('/datasets', {method:'POST',body:JSON.stringify(body)}),
  updateDataset: (id:string, body:Record<string, unknown>) => request<any>(`/datasets/${id}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteDataset: (id:string) => request<void>(`/datasets/${id}`, {method:'DELETE'}),
  datasetCreators: () => request<any>('/datasets/creators'),
  copyDataset: (id:string, includeAssets:boolean, name:string) => request<any>(`/datasets/${id}/copy`, {method:'POST',body:JSON.stringify({include_assets:includeAssets,name})}),
  datasetTagDistribution: (id:string) => request<any>(`/datasets/${id}/tag-distribution`),
  datasetMembers: (id:string, page=1, pageSize=50, filters=new URLSearchParams()) => request<any>(`/datasets/${id}/members?page=${page}&page_size=${pageSize}&${filters}`),
  datasetMemberStatus: (id:string, assetIds:string[]) => request<{existing_ids:string[]}>(`/datasets/${id}/members/status`, {method:'POST',body:JSON.stringify({asset_ids:assetIds})}),
  addDatasetMembers: (id:string, assetIds:string[]) => request<any>(`/datasets/${id}/members`, {method:'POST',body:JSON.stringify({asset_ids:assetIds})}),
  previewDatasetMembers: (id:string, assetIds:string[], action:'add'|'remove') => request<any>(`/datasets/${id}/members/preview?action=${action}`, {method:'POST',body:JSON.stringify({asset_ids:assetIds})}),
  removeDatasetMembers: (id:string, assetIds:string[]) => request<any>(`/datasets/${id}/members`, {method:'DELETE',body:JSON.stringify({asset_ids:assetIds})}),
  datasetVersion: (id:string, versionId:string) => request<any>(`/datasets/${id}/versions/${versionId}`),
  datasetVersions: (id:string) => request<any>(`/datasets/${id}/versions`),
  datasetModels: (id:string) => request<any>(`/datasets/${id}/models`),
  addDatasetModel: (id:string, body:Record<string,unknown>) => request<any>(`/datasets/${id}/models`, {method:'POST',body:JSON.stringify(body)}),
  removeDatasetModel: (id:string, relationId:string) => request<any>(`/datasets/${id}/models/${relationId}`, {method:'DELETE'}),
  publishDatasetVersion: (id:string, version:string, releaseNote:string) => request<any>(`/datasets/${id}/versions`, {method:'POST',body:JSON.stringify({version,release_note:releaseNote})}),
  compareDatasetVersions: (id:string, fromId:string, toId:string) => request<any>(`/datasets/${id}/compare?from_version_id=${encodeURIComponent(fromId)}&to_version_id=${encodeURIComponent(toId)}`),
  restoreDatasetVersion: (id:string, versionId:string) => request<any>(`/datasets/${id}/restore`, {method:'POST',body:JSON.stringify({version_id:versionId})}),
  exportDataset: (id:string, name?:string) => request<any>(`/datasets/${id}/export`, {method:'POST',body:JSON.stringify({name:name||null})}),
  savedViews: () => request<any>('/saved-views'),
  createSavedView: (body:Record<string, unknown>) => request<any>('/saved-views', {method:'POST',body:JSON.stringify(body)}),
  updateSavedView: (id:string, name:string) => request<any>(`/saved-views/${id}`, {method:'PATCH',body:JSON.stringify({name})}),
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
  createUser: (body:Record<string, unknown>) => request<any>('/users', {method:'POST',body:JSON.stringify(body)}),
  updateUser: (id:string, body:Record<string, unknown>) => request<any>(`/users/${id}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteUser: (id:string) => request<void>(`/users/${id}`, {method:'DELETE'}),
  formats: () => request<any>('/format-definitions'),
  createFormat: (body:Record<string, unknown>) => request<any>('/format-definitions', {method:'POST',body:JSON.stringify(body)}),
  updateFormat: (type:string, body:Record<string, unknown>) => request<any>(`/format-definitions/${encodeURIComponent(type)}`, {method:'PATCH',body:JSON.stringify(body)}),
  deleteFormat: (type:string) => request<void>(`/format-definitions/${encodeURIComponent(type)}`, {method:'DELETE'}),
  auditLogs: () => request<any>('/audit-logs?page_size=20'),
}
