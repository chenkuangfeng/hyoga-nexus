/**
 * Sidebar navigation: groups and their pages. Admin-only groups are hidden for other users, and the
 * router redirects them away from admin paths (see `requiresAdmin`).
 */
/** `labelKey` is a key under `shell.pages` in the i18n messages; labels are translated where shown. */
export interface NavItem { path: string; labelKey: string }
export interface NavGroup { titleKey: string; items: NavItem[]; requiresAdmin?: boolean }

export const navigation: NavGroup[] = [
  { titleKey: 'shell.groups.workbench', items: [{ path: '/chat', labelKey: 'shell.pages.chat' }] },
  { titleKey: 'shell.groups.space', items: [
    { path: '/space/organization', labelKey: 'shell.pages.spaceOrganization' },
    { path: '/space/roles', labelKey: 'shell.pages.spaceRoles' },
    { path: '/space/models', labelKey: 'shell.pages.spaceModels' },
  ] },
  { titleKey: 'shell.groups.personal', items: [
    { path: '/personal/native', labelKey: 'shell.pages.personalNative' },
    { path: '/personal/account', labelKey: 'shell.pages.personalAccount' },
  ] },
  { titleKey: 'shell.groups.platform', requiresAdmin: true, items: [
    { path: '/admin/organizations', labelKey: 'shell.pages.adminOrganizations' },
    { path: '/admin/sessions', labelKey: 'shell.pages.adminSessions' },
    { path: '/admin/overview', labelKey: 'shell.pages.adminOverview' },
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
