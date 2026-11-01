/**
 * Sidebar navigation: groups and their pages. Admin-only groups are hidden for other users, and the
 * router redirects them away from admin paths (see `requiresAdmin`).
 */
export interface NavItem { path: string; label: string }
export interface NavGroup { title: string; items: NavItem[]; requiresAdmin?: boolean }

export const navigation: NavGroup[] = [
  { title: '工作台', items: [{ path: '/chat', label: '对话' }] },
  { title: '空间', items: [
    { path: '/space/organization', label: '空间组织' },
    { path: '/space/roles', label: '角色与权限' },
    { path: '/space/models', label: '模型设置' },
  ] },
  { title: '个人', items: [
    { path: '/personal/native', label: 'Native 与记忆' },
    { path: '/personal/account', label: '我的账号' },
  ] },
  { title: '平台管理', requiresAdmin: true, items: [
    { path: '/admin/organizations', label: '组织与人员' },
    { path: '/admin/sessions', label: '会话查询' },
    { path: '/admin/overview', label: '平台能力' },
  ] },
]

/** Former hash pages (`#name`) and where they live now, so existing bookmarks keep working. */
export const legacyHashRoutes: Record<string, string> = {
  chat: '/chat',
  settings: '/space/models',
  roles: '/space/roles',
  'space-org': '/space/organization',
  orgs: '/admin/organizations',
  'admin-sessions': '/admin/sessions',
  account: '/personal/account',
  'native-settings': '/personal/native',
  overview: '/admin/overview',
}
