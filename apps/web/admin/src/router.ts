import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@nexus-web/core/stores/auth'

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
        window.location.replace(to.fullPath)
        return false
      },
    })),
    { path: '/', component: () => import('./Home.vue') },
    { path: '/:pathMatch(.*)*', component: () => import('@nexus-web/core/components/NotFound.vue'), meta: { public: true } },
  ],
})
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!localStorage.getItem('weknora_token')) return '/login'
  try {
    if (!await auth.refreshFromAuthMe()) return '/login'
  } catch {
    return '/login'
  }
  if (auth.user?.must_change_password && to.path !== '/auth/change-password') return '/auth/change-password'
  return true
})
export default router
