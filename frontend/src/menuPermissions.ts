export type MenuKey = 'overview' | 'project_overview' | 'library' | 'datasets' | 'relations' | 'lineage' | 'downloads' | 'trash' | 'tags' | 'formats' | 'parameters' | 'admin' | 'roles' | 'logs'
export type ActionKey = 'asset_upload' | 'asset_edit' | 'asset_delete' | 'saved_view_manage' | 'dataset_create_edit' | 'dataset_members_manage' | 'dataset_version_publish' | 'dataset_version_restore' | 'dataset_delete' | 'dataset_model_manage' | 'relation_manage' | 'relation_revoke' | 'export_create' | 'trash_manage' | 'tag_manage' | 'format_manage' | 'parameter_manage' | 'user_manage' | 'role_manage'

export function resolveMenuPermissions(
  user: { roles?: string[]; menu_permissions?: string[] } | null | undefined,
  rolePermissions: Record<string, MenuKey[]>,
): MenuKey[] {
  const permissions = new Set<MenuKey>()
  for (const role of user?.roles || []) {
    const values = role === 'custom' ? (user?.menu_permissions || []) : (rolePermissions[role] || [])
    for (const value of values) {
      if (['overview','project_overview','library','datasets','relations','lineage','downloads','trash','tags','formats','parameters','admin','roles','logs'].includes(value)) {
        permissions.add(value as MenuKey)
      }
    }
  }
  return [...permissions]
}

export function resolveActionPermissions(
  user: { roles?: string[]; action_permissions?: string[] } | null | undefined,
  rolePermissions: Record<string, ActionKey[]>,
): ActionKey[] {
  const permissions = new Set<ActionKey>()
  for (const role of user?.roles || []) {
    const values = role === 'custom' ? (user?.action_permissions || []) : (rolePermissions[role] || [])
    for (const value of values) permissions.add(value as ActionKey)
  }
  return [...permissions]
}
