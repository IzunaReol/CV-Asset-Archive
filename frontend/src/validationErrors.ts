type ValidationIssue = {
  loc?: unknown[]
  type?: string
  msg?: string
  ctx?: Record<string, unknown>
}

const fieldNames: Record<string, string> = {
  username: '用户名', password: '密码', key: '内部标识', name: '名称',
  version: '版本号', color: '颜色值', remark: '备注', description: '说明',
  projects: '所属项目', values: '标签值', extensions: '文件格式',
}

export function formatValidationErrors(detail: unknown): string {
  if (!Array.isArray(detail)) return ''
  return detail.map((issue: ValidationIssue) => {
    const field = [...(issue.loc || [])].reverse().find(value => typeof value === 'string' && value !== 'body')
    const label = fieldNames[String(field || '')] || '输入内容'
    const limit = issue.ctx?.max_length ?? issue.ctx?.min_length
    if (issue.type === 'missing') return `${label}为必填项`
    if (issue.type === 'string_pattern_mismatch' || issue.type === 'literal_error' || issue.type === 'enum') return `${label}格式不正确`
    if (issue.type === 'string_too_long') return `${label}不能超过 ${limit ?? '规定数量的'} 个字符`
    if (issue.type === 'string_too_short') return `${label}至少需要 ${limit ?? '规定数量的'} 个字符`
    if (issue.type === 'too_long') return `${label}不能超过 ${limit ?? '规定数量的'} 项`
    if (issue.type === 'too_short') return `${label}至少需要 ${limit ?? '规定数量的'} 项`
    if (issue.msg && /[\u4e00-\u9fff]/.test(issue.msg)) return issue.msg.replace(/^Value error,\s*/, '')
    return `${label}不符合要求`
  }).join('；')
}
