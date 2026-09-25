export type PollState = {
  page: string
  jobs: Array<{ state?: string }>
  assets: Array<{ status?: string }>
}

export function jobPollDelay({ page, jobs, assets }: PollState): number {
  if (page === 'downloads' && jobs.some(job => ['queued', 'running'].includes(job.state || ''))) return 3000
  if (page === 'library' && assets.some(asset => ['queued', 'processing'].includes(asset.status || ''))) return 3000
  return page === 'downloads' ? 15000 : 30000
}

export function persistedSession<T extends { user: unknown; access_expires_at: string }>(tokens: T) {
  return {
    access_token: '',
    access_expires_at: tokens.access_expires_at,
    user: tokens.user,
  }
}
