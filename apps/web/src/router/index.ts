/**
 * Browser-history routes for the workbench. Login is not a route: `App.vue` shows the login form
 * whenever no session exists, so every path can be reloaded and the user returns to it after signing in.
 */
import { createRouter, createWebHistory } from 'vue-router'
import ConversationView from '../views/chat/ConversationView.vue'
import SpaceOrganizationView from '../views/settings/SpaceOrganizationView.vue'
import RoleManagementView from '../views/settings/RoleManagementView.vue'
import ModelSettingsView from '../views/settings/ModelSettingsView.vue'
import NativeSettingsView from '../views/settings/NativeSettingsView.vue'
import AccountView from '../views/auth/AccountView.vue'
import OrganizationManagementView from '../views/settings/OrganizationManagementView.vue'
import AdminSessionsView from '../views/settings/AdminSessionsView.vue'
import OverviewView from '../views/OverviewView.vue'
import { legacyHashRoutes } from './navigation'
import { workspace } from '../stores/workspace'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    // Rendered by App.vue while signed out (its query carries login errors); nothing to render here.
    { path: '/login', name: 'login', component: { render: () => null }, meta: { title: '登录', public: true } },
    { path: '/chat/:sessionId?', name: 'chat', component: ConversationView, meta: { title: '对话' } },
    { path: '/space/organization', name: 'space-organization', component: SpaceOrganizationView, meta: { title: '空间组织' } },
    { path: '/space/roles', name: 'space-roles', component: RoleManagementView, meta: { title: '角色与权限' } },
    { path: '/space/models', name: 'space-models', component: ModelSettingsView, meta: { title: '模型设置' } },
    { path: '/personal/native', name: 'personal-native', component: NativeSettingsView, meta: { title: 'Native 与记忆' } },
    {
      path: '/personal/account', name: 'personal-account', component: AccountView, meta: { title: '我的账号' },
      // The account page receives the signed-in user and the WeCom binding result from the redirect query (`?wecom=...`).
      props: route => ({ user: workspace.user, wecomResult: String(route.query.wecom || '') }),
    },
    { path: '/admin/organizations', name: 'admin-organizations', component: OrganizationManagementView, meta: { title: '组织与人员', requiresAdmin: true } },
    { path: '/admin/sessions', name: 'admin-sessions', component: AdminSessionsView, meta: { title: '会话查询', requiresAdmin: true } },
    { path: '/admin/overview', name: 'admin-overview', component: OverviewView, meta: { title: '平台能力', requiresAdmin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

/** `/#name?query` links from before the router was introduced are rewritten to the new paths. */
export function redirectLegacyHash(): void {
  const match = /^#([a-z-]+)(\?.*)?$/.exec(location.hash)
  const target = match && legacyHashRoutes[match[1]]
  if (target) void router.replace(target + (match?.[2] || ''))
}
