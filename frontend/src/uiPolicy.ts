export type JobAction = 'download' | 'retry' | 'cancel' | null

export function canDeleteTag(tag: { built_in?: boolean }): boolean {
  return !tag.built_in
}

export function jobAction(job: { state?: string; type?: string }): JobAction {
  if (job.state === 'succeeded' && ['export', 'dataset_export'].includes(job.type || '')) return 'download'
  if (job.state === 'failed') return 'retry'
  if (['queued', 'running'].includes(job.state || '') && ['export', 'dataset_export'].includes(job.type || '')) return 'cancel'
  return null
}
