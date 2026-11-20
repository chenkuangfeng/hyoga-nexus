import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from './stores/context'

/** 开发时员工应用使用同主机 5173 端口；生产部署保持同源路径并保留查询参数。 */
function workspaceLocation(path = '/'): string {
  if (!import.meta.env.DEV) return path
  const url = new URL(path, window.location.origin)
  url.port = '5173'
  return url.href
}

/** 管理应用只消费服务端 entries；具体操作仍由各接口校验权限。 */
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', component: () => import('@nexus-web/core/views/auth/Login.vue'), meta: { public: true } },
    { path: '/auth/change-password', component: () => import('@nexus-web/core/views/auth/ChangePassword.vue') },
    // 邀请和无企业身份的开户流程属于员工应用，跨应用跳转保留完整查询参数。
    ...['/join', '/onboarding/workspace'].map(path => ({
      path,
      // 路由需要可匹配的组件记录；导航守卫会在挂载前转交员工应用。
      component: { render: () => null },
      meta: { public: true },
      beforeEnter(to: { fullPath: string }) {
        window.location.replace(workspaceLocation(to.fullPath))
        return false
      },
    })),
    { path: '/', component: () => import('./AdminLayout.vue'), children: [
      { path: '', redirect: '/settings' },
      { path: 'enterprise', component: () => import('./views/EnterpriseSpacePage.vue') },
      { path: 'organization', component: () => import('./views/organization/OrganizationPage.vue') },
      { path: 'wecom', component: () => import('./views/organization/WecomPage.vue') },
      { path: 'members', component: () => import('./views/members/MembersPage.vue'), props: () => ({ workspaceHref: workspaceLocation() }) },
      { path: 'roles', component: () => import('./views/roles/RolesPage.vue') },
      { path: 'settings', component: () => import('./views/SystemSettingsPage.vue') },
      { path: 'skills', component: () => import('./views/skills/SkillsPage.vue') },
      { path: 'models', component: () => import('./views/models/ModelsPage.vue') },
      { path: 'usage', component: () => import('./views/usage/UsagePage.vue') },
      { path: 'runtime', component: () => import('./views/runtime/RuntimeHealthPage.vue') },
      { path: 'mcp-endpoints', component: () => import('./views/connections/EndpointsPage.vue') },
      { path: 'mcp-services', component: () => import('./views/connections/McpServicesPage.vue') },
      { path: 'parsers', component: () => import('./views/parsers/ParserPage.vue') },
      { path: 'storage', component: () => import('./views/storage/StoragePage.vue') },
      { path: 'vector-stores', component: () => import('./views/storage/VectorStoresPage.vue') },
      { path: 'graph-stores', component: () => import('./views/storage/GraphStoresPage.vue') },
      { path: 'knowledge', component: () => import('./views/knowledge/KnowledgePage.vue') },
      { path: 'knowledge/:kbId/content', component: () => import('./views/knowledge/KnowledgeContentPage.vue') },
      { path: 'agents', component: () => import('./views/agents/AgentsPage.vue') },
      { path: 'channels', component: () => import('./views/agents/ChannelsPage.vue') },
      { path: 'skill-submissions', component: () => import('./views/skills/SkillSubmissionsPage.vue') },
      { path: 'tools', component: () => import('./views/tools/ToolCatalogPage.vue') },
      { path: 'audit', component: () => import('./views/audit/AuditPage.vue') },
      { path: 'policy', component: () => import('./views/EnterprisePolicy.vue') },
    ] },
    { path: '/:pathMatch(.*)*', component: () => import('@nexus-web/core/components/NotFound.vue'), meta: { public: true } },
  ],
})
let navigationSequence = 0
router.beforeEach(async (to, from) => {
  const navigation = ++navigationSequence
  const auth = useAuthStore()
  if (to.meta.public) return true
  // 只跳过同页编辑历史变化；其他业务导航继续校准身份与权限。
  if (to.path === from?.path && to.query.editor !== from.query.editor && !auth.user?.must_change_password
    && [...new Set([...Object.keys(to.query), ...Object.keys(from.query)])].filter(key => key !== 'editor').every(key => JSON.stringify(to.query[key]) === JSON.stringify(from.query[key]))
    && localStorage.getItem('weknora_token') && useAdminContext().ready) return true
  const context = useAdminContext()
  if (!localStorage.getItem('weknora_token')) {
    context.invalidate()
    return '/login'
  }
  const refreshOptions = { preserveNavigation: true }
  context.invalidate(refreshOptions)
  const authenticated = await auth.refreshFromAuthMe().catch(() => false)
  // 侧栏在校验期间仍可点击，旧导航不能覆盖后续导航的校验状态。
  if (navigation !== navigationSequence) return false
  if (!authenticated) {
    context.invalidate()
    return '/login'
  }
  if (auth.user?.must_change_password && to.path !== '/auth/change-password') {
    context.invalidate()
    return '/auth/change-password'
  }
  await context.load(refreshOptions)
  return true
})
export default router
