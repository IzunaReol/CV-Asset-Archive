const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

type Tokens = { access_token:string; refresh_token:string; access_expires_at:string; user:Record<string, unknown> }

let tokens: Tokens | null = JSON.parse(localStorage.getItem('cv-archive-session') || 'null')
let refreshPromise: Promise<boolean> | null = null

function saveTokens(next: Tokens | null) {
  tokens = next
  if (next) localStorage.setItem('cv-archive-session', JSON.stringify(next))
  else localStorage.removeItem('cv-archive-session')
}

async function refreshSession(): Promise<boolean> {
  if (!tokens?.refresh_token) return false
  if (!refreshPromise) {
    const refreshToken = tokens.refresh_token
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method:'POST',
      headers:{'content-type':'application/json'},
      body:JSON.stringify({refresh_token:refreshToken}),
    }).then(async (response) => {
      if (!response.ok) {
        saveTokens(null)
        return false
      }
      saveTokens(await response.json())
      return true
    }).catch(() => false).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('content-type')) headers.set('content-type', 'application/json')
  if (tokens?.access_token) headers.set('authorization', `Bearer ${tokens.access_token}`)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  } catch {
    throw new Error('无法连接至服务器，请重启后端服务')
  }
  if (response.status === 401 && retry && tokens?.refresh_token) {
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
  login: async (username:string, password:string) => {
    const result = await request<Tokens>('/auth/login', {method:'POST', body:JSON.stringify({username,password})}, false)
    saveTokens(result)
    return result
  },
  logout: async () => {
    if (tokens?.refresh_token) await request('/auth/logout', {method:'POST', body:JSON.stringify({refresh_token:tokens.refresh_token})}).catch(() => undefined)
    saveTokens(null)
  },
  assets: (params:URLSearchParams) => request<{items:any[];total:number}>(`/assets?${params}`),
  assetStats: () => request<{total:number;untagged:number;by_type:Record<string,number>;storage:{total:number;used:number;free:number}}>('/assets/stats'),
  asset: (id:string) => request<any>(`/assets/${id}`),
  updateAssetRemark: (id:string, remark:string) => request<any>(`/assets/${id}/remark`, {method:'PATCH',body:JSON.stringify({remark})}),
  annotationOverlays: (id:string) => request<any>(`/assets/${id}/annotation-overlays`),
  archiveAsset: (id:string) => request<any>(`/assets/${id}/archive`, {method:'POST'}),
  initUpload: (body:Record<string, unknown>) => request<any>('/assets/upload-sessions', {method:'POST',body:JSON.stringify(body)}),
  completeUpload: (body:Record<string, unknown>) => request<any>('/assets/upload-sessions/complete', {method:'POST',body:JSON.stringify(body)}),
  batchTags: (body:Record<string, unknown>) => request<any>('/assets/batch-tags', {method:'POST',body:JSON.stringify(body)}),
  batchDelete: (assetIds:string[]) => request<any>('/assets/batch-delete', {method:'POST',body:JSON.stringify({asset_ids:assetIds})}),
  trash: (page=1,pageSize=50) => request<any>(`/assets/trash/items?page=${page}&page_size=${pageSize}`),
  restoreTrash: (assetIds:string[]) => request<any>('/assets/trash/restore', {method:'POST',body:JSON.stringify({asset_ids:assetIds})}),
  emptyTrash: () => request<any>('/assets/trash/empty', {method:'POST'}),
  job: (id:string) => request<any>(`/jobs/${id}`),
  relations: (page:number, pageSize:number, filters:Record<string,string>={}) => {
    const params = new URLSearchParams({page:String(page),page_size:String(pageSize),...filters})
    return request<any>(`/relations?${params}`)
  },
  relation: (id:string) => request<any>(`/relations/${id}`),
  relationGraph: (id:string) => request<any>(`/relations/graph/${encodeURIComponent(id)}?depth=4`),
  previewRelations: (body:Record<string, unknown>) => request<any>('/relations/preview', {method:'POST',body:JSON.stringify(body)}),
  previewAnnotationMatches: (body:Record<string, unknown>) => request<any>('/relations/annotation-match-preview', {method:'POST',body:JSON.stringify(body)}),
  createRelations: (body:Record<string, unknown>) => request<any>('/relations/batch', {method:'POST',body:JSON.stringify(body)}),
  revokeRelation: (id:string, reason:string) => request<any>(`/relations/${id}/revoke`, {method:'POST',body:JSON.stringify({reason})}),
  collections: () => request<any>('/collections'),
  createCollection: (body:Record<string, unknown>) => request<any>('/collections', {method:'POST',body:JSON.stringify(body)}),
  savedViews: () => request<any>('/saved-views'),
  createSavedView: (body:Record<string, unknown>) => request<any>('/saved-views', {method:'POST',body:JSON.stringify(body)}),
  updateSavedView: (id:string, name:string) => request<any>(`/saved-views/${id}`, {method:'PATCH',body:JSON.stringify({name})}),
  deleteSavedView: (id:string) => request<void>(`/saved-views/${id}`, {method:'DELETE'}),
  createExport: (body:Record<string, unknown>) => request<any>('/exports', {method:'POST',body:JSON.stringify(body)}),
  jobs: (type?:string) => request<any>(`/jobs${type ? `?type=${encodeURIComponent(type)}` : ''}`),
  retryJob: (id:string) => request<any>(`/jobs/${id}/retry`, {method:'POST'}),
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
