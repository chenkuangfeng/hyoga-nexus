import { createRouter, createWebHistory } from 'vue-router'
import { defineComponent } from 'vue'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useDeploymentCapabilitiesStore } from '@/stores/deploymentCapabilities'
import type { DeploymentCapabilityKey } from '@/config/deploymentCapabilities'
import { MessagePlugin } from 'tdesign-vue-next'
import i18n from '@nexus-web/core/i18n/index'
import { normalizeSettingsSection } from '@/config/settingsRoute'
import { isToolboxSection, toolboxLocation } from '@/config/toolbox'
import PlannedPage from '@/views/placeholder/PlannedPage.vue'
// 主对话页：WeKnora 风格布局 + 平台 Native API（会话、Run、事件）。
const NexusChatRoutePage = () => import('@/views/chat/NexusChatRoutePage.vue')

// views/platform/index.vue always mounts the settings modal and opens it when
// the path is /platform/settings, so this route only has to own the URL.
// Rendering Settings.vue here would mount a second, independent copy.
const SettingsRouteOutlet = defineComponent({ name: 'SettingsRouteOutlet', render: () => null })

function hasPendingOIDCCallback() {
  if (typeof window === 'undefined') return false
  const hash = window.location.hash || ''
  return hash.includes('oidc_result=') || hash.includes('oidc_error=')
}

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/:pathMatch(.*)*", component: () => import("@nexus-web/core/components/NotFound.vue"), meta: { requiresAuth: false, requiresInit: false } },
    {
      path: "/",
      redirect: "/platform/settings",
    },
    {
      path: "/login",
      name: "login",
      component: () => import("@nexus-web/core/views/auth/Login.vue"),
      meta: { requiresAuth: false, requiresInit: false }
    },
    // Embed chat is a separate entry (embed.html + embed-main.ts), not this SPA.
    {
      path: "/auth/change-password",
      name: "changePassword",
      component: () => import("@nexus-web/core/views/auth/ChangePassword.vue"),
      meta: { requiresAuth: true, requiresInit: false }
    },
    {
      path: "/register",
      name: "registerByInvite",
      // Share-link landing page reuses the Login form: the same Vue
      // component renders both modes and detects ?token=xxx on mount
      // to switch into invite-register flow. Avoids a parallel page
      // that would duplicate the OIDC / language-switch / styling
      // surface for one extra field.
      component: () => import("@nexus-web/core/views/auth/Login.vue"),
      meta: { requiresAuth: false, requiresInit: false }
    },
    {
      path: "/onboarding/workspace",
      name: "workspaceOnboarding",
      component: () => import("../views/auth/WorkspaceOnboarding.vue"),
      meta: { requiresAuth: true, requiresInit: false, requiresTenant: false }
    },
    {
      path: "/join",
      name: "joinOrganization",
      // 邀请入口：`?code=` 为共享空间邀请码，`?token=` 为企业邀请链接（见 JoinEntry.vue）。
      component: () => import("../views/auth/JoinEntry.vue"),
      meta: { requiresInit: false, requiresAuth: false, requiresTenant: false }
    },
    {
      path: "/knowledgeBase",
      name: "home",
      component: PlannedPage,
      meta: { requiresInit: true, requiresAuth: true }
    },
    {
      path: "/platform",
      name: "Platform",
      redirect: "/platform/knowledge-bases",
      component: () => import("../views/platform/index.vue"),
      meta: { requiresInit: true, requiresAuth: true },
      children: [
        {
          path: "tenant",
          redirect: "/platform/settings"
        },
        {
          path: "settings",
          name: "settings",
          component: SettingsRouteOutlet,
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          path: "knowledge-bases",
          name: "knowledgeBaseList",
          // openspec 2026-11-06-knowledge-base K1: WeKnora pages on the Nexus API; planned features are marked.
          component: () => import("../views/knowledge/KnowledgeBaseList.vue"),
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          path: "knowledge-bases/:kbId",
          name: "knowledgeBaseDetail",
          component: () => import("../views/knowledge/KnowledgeBase.vue"),
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          path: "knowledge-search",
          // 旧路径保留为重定向，打开全局命令面板（⌘K），带上可选的 q 参数
          redirect: (to) => {
            const q = to.query.q
            return {
              path: '/platform/knowledge-bases',
              query: typeof q === 'string' ? { cmdk: q } : { cmdk: '' },
            }
          },
        },
        {
          path: "artifacts",
          name: "artifactLibrary",
          // Files Runs left under /outputs, on the Nexus artifacts API (openspec 2026-11-07-tool-expansion 4.6).
          component: () => import("../views/artifacts/ArtifactLibrary.vue"),
          meta: { requiresInit: true, requiresAuth: true, requiredCapability: 'settings.sandbox' }
        },
        {
          path: "toolbox/:section?",
          name: "toolbox",
          component: () => import("../views/toolbox/NexusToolbox.vue"),
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          path: "automations/:automationId?",
          name: "automationList",
          // Scheduled tasks on the Nexus API (openspec 2026-11-07-tool-expansion 8.2a); the WeKnora pages are adapted.
          component: () => import("../views/automation/AutomationList.vue"),
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          // 旧的 Native 运行页已并入主对话页（views/chat/NexusChatPage.vue）；旧地址保留为重定向。
          path: "native",
          redirect: "/platform/creatChat"
        },
        {
          path: "native/sessions/:sessionId",
          redirect: (to) => `/platform/chat/${String(to.params.sessionId)}`
        },
        {
          path: "agents",
          name: "agentList",
          // Nexus agent list and editor (openspec 2026-11-05-weknora-agent-tool-model-settings).
          component: () => import("../views/agent/NexusAgentList.vue"),
          meta: { requiresInit: true, requiresAuth: true, requiredCapability: 'agents' }
        },
        {
          path: "integrations",
          redirect: (to) => {
            const tab = typeof to.query.tab === 'string' ? to.query.tab : undefined
            const incoming = typeof to.query.section === 'string' ? to.query.section : 'integrations'
            const rest = { ...to.query }
            delete rest.tab
            return {
              path: '/platform/settings',
              query: {
                ...rest,
                section: normalizeSettingsSection(incoming, tab),
              },
            }
          },
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          path: "creatChat",
          name: "globalCreatChat",
          component: NexusChatRoutePage,
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          // 会话不挂载知识库（见 openspec/changes/2026-11-04-weknora-chat-dialog 决定 3），直接进入普通新建对话页。
          path: "knowledge-bases/:kbId/creatChat",
          redirect: "/platform/creatChat"
        },
        {
          path: "chat/:chatid",
          name: "chat",
          component: NexusChatRoutePage,
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          path: "shared-spaces",
          name: "sharedSpaces",
          component: () => import("../views/shared-space/SharedSpaceList.vue"),
          meta: { requiresInit: true, requiresAuth: true }
        },
        {
          path: "organizations",
          redirect: "/platform/shared-spaces",
        },
      ],
    },
    // Dev-only markdown rendering test page
    ...(import.meta.env.DEV ? [{
      path: '/platform/dev/markdown',
      name: 'markdownTest',
      component: () => import('../views/dev/MarkdownTestPage.vue'),
      meta: { requiresAuth: false, requiresInit: false }
    }] : []),
  ],
});

async function hydrateSessionFromToken(authStore: ReturnType<typeof useAuthStore>) {
  const token = localStorage.getItem('weknora_token')
  if (!token) return false

  if (!authStore.token) {
    authStore.setToken(token)
  }

  const storedRefreshToken = localStorage.getItem('weknora_refresh_token')
  if (storedRefreshToken && !authStore.refreshToken) {
    authStore.setRefreshToken(storedRefreshToken)
  }

  // /auth/me 的落库逻辑只在 auth store 里维护一份（user / tenant / memberships /
  // capabilities），这里只负责先把 token 放进 store。请求本身与启动、侧栏共用去重。
  return authStore.refreshFromAuthMe()
}

// 路由守卫：检查认证状态和系统初始化状态
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // OIDC 回跳登录结果依赖 App.vue 在挂载后消费 URL hash。
  // 如果这里先按“未登录”拦截到 /login，会导致回调结果没有机会落盘。
  if (hasPendingOIDCCallback()) {
    next()
    return
  }

  // Preserve bookmarks for tools that have moved out of Settings.
  if (to.path === '/platform/settings' && isToolboxSection(to.query.section)) {
    next({ ...toolboxLocation(to.query.section,
      typeof to.query.sandboxId === 'string' ? to.query.sandboxId : undefined), replace: true })
    return
  }

  // Tenantless onboarding still requires a valid user token even though it
  // deliberately skips the normal tenant/system-initialization gates.
  if (to.path === '/onboarding/workspace') {
    if (!authStore.isLoggedIn) {
      const restored = await hydrateSessionFromToken(authStore)
      if (!restored) {
        next('/login')
        return
      }
    }
    if (authStore.hasValidTenant) {
      next('/platform/knowledge-bases')
    } else {
      next()
    }
    return
  }

  // 如果访问的是登录页面或初始化页面，直接放行
  if (to.meta.requiresAuth === false) {
    // 如果已登录用户访问登录页面，重定向到知识库列表页面
    if (to.path === '/login' && authStore.isLoggedIn) {
      next(authStore.hasValidTenant ? '/platform/knowledge-bases' : '/onboarding/workspace')
      return
    }
    next()
    return
  }

  // 检查用户认证状态
  if (to.meta.requiresAuth !== false) {
    if (!authStore.isLoggedIn) {
      const restored = await hydrateSessionFromToken(authStore)
      if (restored) {
        next(
          !authStore.hasValidTenant && to.meta.requiresTenant !== false
            ? '/onboarding/workspace'
            : to.fullPath,
        )
        return
      }
      next('/login')
      return
    }
  }

  if (authStore.user?.must_change_password && to.path !== '/auth/change-password') {
    next('/auth/change-password')
    return
  }
  if (to.path === '/auth/change-password') {
    next()
    return
  }

  if (to.meta.requiresTenant !== false && !authStore.hasValidTenant) {
    next('/onboarding/workspace')
    return
  }

  // 部署能力只描述“后端是否提供该功能”，不反映服务健康或是否已配置。
  // 探测失败时 Store 会 fail-open，真正的权限和可用性仍由后端接口校验。
  const deploymentCapabilities = useDeploymentCapabilitiesStore()
  await deploymentCapabilities.ensureLoaded()
  const requiredCapability = to.meta.requiredCapability as DeploymentCapabilityKey | undefined
  if (requiredCapability && !deploymentCapabilities.isSupported(requiredCapability)) {
    MessagePlugin.warning(i18n.global.t('settings.capabilityUnavailable'))
    next('/platform/knowledge-bases')
    return
  }

  next()
})

export default router
