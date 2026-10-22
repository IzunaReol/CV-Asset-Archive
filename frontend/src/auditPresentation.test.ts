import { describe, expect, it } from 'vitest'
import { auditActionText, createAuditPresentation } from './auditPresentation'

const presentation = createAuditPresentation({
  fieldLabels: { roles: '角色', size: '文件大小', action_permissions: '操作权限' },
  objectLabels: { user: '用户' },
  permissionLabels: () => ({ asset_edit: '编辑素材' }),
  roleText: role => ({ viewer: '只读访客' } as Record<string, string>)[role] || role,
  formatStorageSize: size => `${size} B`,
})

describe('系统日志展示格式', () => {
  it('转换操作、对象和权限变更', () => {
    expect(auditActionText('user.updated')).toBe('修改用户')
    expect(auditActionText('metric_category.deleted')).toBe('删除指标分类')
    expect(auditActionText('unknown')).toBe('unknown')
    expect(presentation.objectText({ object_type: 'user', object_name: '张三' })).toBe('用户：张三')
    expect(presentation.objectText({ object_type: 'other' })).toBe('其他：未命名对象')
    expect(presentation.changeEntries({ roles: ['viewer'], action_permissions: ['asset_edit'], size: 1024 })).toEqual([
      { key: 'roles', label: '角色', value: '只读访客' },
      { key: 'action_permissions', label: '操作权限', value: '编辑素材' },
      { key: 'size', label: '文件大小', value: '1024 B' },
    ])
  })

  it('对空值、布尔值、数组和长变更摘要保持可读', () => {
    expect(presentation.changesText({})).toBe('未记录字段变化')
    expect(presentation.valueText('flag', false)).toBe('否')
    expect(presentation.valueText('asset_ids', ['a', 'b'])).toBe('共 2 项')
    expect(presentation.valueText('nested', { enabled: true })).toBe('enabled：是')
    expect(presentation.changesText({ a: 1, b: 2, c: 3, d: 4 })).toContain('另有 1 项')
  })
})
