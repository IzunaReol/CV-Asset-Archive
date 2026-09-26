export type ApiList<T> = {
  items: T[]
  page: number
  page_size: number
  total: number
}

export type DatasetOption = {
  id: string
  name: string
  current_version?: string | null
  current_version_id: string
}

export type Job = {
  id: string
  name: string
  type: string
  state: string
  progress?: number
  created_at: string
  [key: string]: unknown
}

export type RelationGraph = {
  nodes: Array<Record<string, unknown>>
  edges: Array<Record<string, unknown>>
  member_total: number
  members_truncated: boolean
  member_limit: number
}

export type AssetStats = {
  total: number
  untagged: number
  by_type: Record<string, number>
  storage: { total: number; used: number; free: number }
}
