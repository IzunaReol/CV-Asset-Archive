export type AuditPresentationDependencies = {
  fieldLabels: Record<string, string>
  objectLabels: Record<string, string>
  permissionLabels: () => Record<string, string>
  roleText: (role: string) => string
  formatStorageSize: (bytes: number) => string
}
export const auditActionLabels: Record<string,string> = {
  'asset.created':'创建素材', 'asset.overwritten':'覆盖素材', 'asset.deleted':'删除素材',
  'asset.batch_deleted':'移入回收站', 'asset.batch_restored':'还原素材',
  'asset.remark_updated':'修改素材备注', 'asset.tags_updated':'修改素材标签', 'asset.batch_tags':'批量修改素材标签',
  'asset.model_parameters_updated':'配置模型参数',
  'trash.emptied':'清空回收站', 'export.created':'创建导出任务',
  'dataset.export_created':'创建数据集导出', 'job.cancelled':'取消任务',
  'relation.created':'建立关联关系', 'relation.revoked':'撤销关联关系',
  'dataset.created':'创建数据集', 'dataset.updated':'修改数据集', 'dataset.deleted':'删除数据集',
  'dataset.members_added':'添加数据集成员', 'dataset.members_removed':'移除数据集成员',
  'dataset.version_published':'发布数据集版本', 'dataset.version_restored':'恢复数据集版本',
  'dataset.model_link_created':'关联数据集模型', 'dataset.model_link_removed':'移除数据集模型关联',
  'collection.created':'创建集合', 'collection.frozen':'冻结集合',
  'saved_view.created':'创建保存视图', 'saved_view.updated':'修改保存视图', 'saved_view.deleted':'删除保存视图',
  'user.created':'创建用户', 'user.updated':'修改用户', 'user.deleted':'删除用户',
  'tag_definition.created':'创建标签', 'tag_definition.updated':'修改标签', 'tag_definition.deleted':'删除标签',
  'format.created':'创建格式', 'format.updated':'修改格式', 'format.deleted':'删除格式',
  'metric_definition.created':'新增指标', 'metric_definition.updated':'修改指标', 'metric_definition.deleted':'删除指标',
  'metric_category.created':'新增指标分类', 'metric_category.updated':'修改指标分类', 'metric_category.deleted':'删除指标分类',
  'role_template.created':'创建角色', 'role_template.updated':'修改角色', 'role_template.deleted':'删除角色',
  'auth.login_succeeded':'登录成功', 'auth.login_failed':'登录失败', 'auth.login_blocked':'登录受限', 'auth.logout':'退出登录', 'auth.permission_denied':'权限拦截', 'auth.session_invalid':'登录状态失效',
  'system.service_unavailable':'服务不可用', 'system.service_recovered':'服务已恢复', 'job.stale_recovered':'异常任务已恢复',
}
export const auditObjectLabels: Record<string,string> = {asset:'素材',dataset:'数据集',dataset_version:'数据集版本',relation:'关联关系',job:'任务',user:'用户',role_template:'角色',tag_definition:'标签',format_definition:'格式',metric_definition:'指标',metric_category:'指标分类',collection:'集合',saved_view:'保存视图',system:'系统'}
export const auditFieldLabels: Record<string,string> = {
  username:'用户名', roles:'角色', menu_permissions:'菜单权限', action_permissions:'操作权限', status:'状态', password_changed:'是否修改密码', description:'说明',
  filename:'文件名', size:'文件大小', mime_type:'文件类型', remark:'备注', tags:'标签', values:'可选值', name:'名称',
  asset_count:'素材数量', count:'处理数量', added:'新增数量', removed:'移除数量', created:'创建数量', revoked:'撤销数量',
  versions_deleted:'删除版本数', relations_deleted:'删除关系数', relations_preserved:'是否保留关联关系', reason:'撤销原因',
  dataset_effects:'数据集影响', shared_scope:'共享范围', visibility:'可见范围', type:'类型', state:'任务状态',
  asset_ids:'涉及素材', invalid_ids:'无效素材', dataset_id:'数据集编号', version_id:'版本编号', selection_id:'选择范围编号',
  upload_session_id:'上传会话编号', previous_object_key:'原文件位置', new_object_key:'新文件位置',
}
export function auditActionText(action: string) { return auditActionLabels[action] || action }

export function createAuditPresentation(deps: AuditPresentationDependencies) {
  function fieldText(key: string) { return deps.fieldLabels[key] || key.replaceAll('_', ' ') }
  function valueText(key: string, value: unknown): string {
    if (value === null || value === undefined || value === '') return '无'
    if (typeof value === 'boolean') return value ? '是' : '否'
    if (key === 'size' && Number.isFinite(Number(value))) return deps.formatStorageSize(Number(value))
    if (Array.isArray(value)) {
      if (key.endsWith('_ids')) return value.length ? `共 ${value.length} 项` : '无'
      if (key === 'roles') return value.map(item => deps.roleText(String(item))).join('、') || '无'
      if (key === 'menu_permissions' || key === 'action_permissions') return value.map(item => deps.permissionLabels()[String(item)] || String(item)).join('、') || '无'
      return value.map(item => valueText(key, item)).join('、') || '无'
    }
    if (typeof value === 'object') return Object.entries(value).map(([childKey, childValue]) => `${fieldText(childKey)}：${valueText(childKey, childValue)}`).join('；') || '无'
    const text = String(value)
    return ({ active: '正常', disabled: '已停用', queued: '等待处理', running: '处理中', succeeded: '已完成', failed: '失败', cancelled: '已取消', private: '仅自己可见', team: '团队成员可见' } as Record<string, string>)[text] || text
  }
  function changeEntries(changes: Record<string, unknown> | null | undefined) {
    return Object.entries(changes || {}).map(([key, value]) => ({ key, label: fieldText(key), value: valueText(key, value) }))
  }
  function changesText(changes: Record<string, unknown> | null | undefined) {
    const entries = changeEntries(changes)
    if (!entries.length) return '未记录字段变化'
    const summary = entries.slice(0, 3).map(item => `${item.label}：${item.value}`).join('；')
    return entries.length > 3 ? `${summary}；另有 ${entries.length - 3} 项` : summary
  }
  function objectText(item: { object_type: string; object_name?: string }) {
    return `${deps.objectLabels[item.object_type] || '其他'}：${item.object_name || '未命名对象'}`
  }
  return { fieldText, valueText, changeEntries, changesText, objectText }
}
