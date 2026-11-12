import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@nexus-web/core/stores/auth'

/** 管理应用只消费服务端 entries；具体操作仍由各接口校验权限。 */
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', component: () => import('@nexus-web/core/views/auth/Login.vue'), meta: { public: true } },
    { path: '/auth/change-password', component: () => import('@nexus-web/core/views/auth/ChangePassword.vue') },
    { path: '/:pathMatch(.*)*', component: () => import('./Home.vue') },
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
