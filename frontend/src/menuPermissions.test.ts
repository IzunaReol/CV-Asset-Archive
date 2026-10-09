import { describe, expect, it } from 'vitest'
import { resolveActionPermissions, resolveMenuPermissions, type ActionKey, type MenuKey } from './menuPermissions'

const rolePermissions: Record<string, MenuKey[]> = {
  viewer: ['library', 'datasets'],
  custom: [],
}

describe('resolveMenuPermissions', () => {
  it('uses the predefined permissions for a fixed role', () => {
    expect(resolveMenuPermissions({ roles: ['viewer'] }, rolePermissions)).toEqual(['library', 'datasets'])
  })

  it('uses only the selected permissions for a custom role', () => {
    expect(resolveMenuPermissions(
      { roles: ['custom'], menu_permissions: ['library', 'downloads'] },
      rolePermissions,
    )).toEqual(['library', 'downloads'])
  })

  it('allows the system log menu to be granted independently', () => {
    expect(resolveMenuPermissions(
      { roles: ['custom'], menu_permissions: ['logs'] }, rolePermissions,
    )).toEqual(['logs'])
  })

  it('ignores invalid stored menu keys', () => {
    expect(resolveMenuPermissions(
      { roles: ['custom'], menu_permissions: ['library', 'unknown'] },
      rolePermissions,
    )).toEqual(['library'])
  })
})

describe('resolveActionPermissions', () => {
  const actions: Record<string, ActionKey[]> = { admin: ['user_manage', 'format_manage'], custom: [] }

  it('uses fixed-role action permissions', () => {
    expect(resolveActionPermissions({ roles: ['admin'] }, actions)).toEqual(['user_manage', 'format_manage'])
  })

  it('uses only explicitly selected actions for a custom role', () => {
    expect(resolveActionPermissions(
      { roles: ['custom'], action_permissions: ['format_manage'] }, actions,
    )).toEqual(['format_manage'])
  })
})
