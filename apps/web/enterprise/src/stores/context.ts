/** 管理端当前企业权限。身份变化同步失效，权限只从服务端读取，不持久化或根据角色推断。 */
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { fetchConnectionPermissions } from '@nexus-web/core/api/enterprise-connections'

interface PermissionRefreshOptions {
  preserveNavigation?: boolean
}

export const useEnterpriseContext = defineStore('enterprise-context', () => {
  const auth = useAuthStore()
  const scope = computed(() => JSON.stringify([auth.user?.id || '', String(auth.effectiveTenantId || '')]))
  const hasEntry = computed(() => auth.currentEntries.includes('enterprise'))
  const permissions = ref<string[]>([]), loading = ref(false), failed = ref(false)
  const navigationPermissions = ref<string[]>([])
  const loadedScope = ref(''), revision = ref(0)
  let epoch = 0
  const ready = computed(() => hasEntry.value && !!loadedScope.value && loadedScope.value === scope.value)
  /** 立即作废业务权限及表单；普通路由校验期间可暂时保留同一身份的菜单。 */
  function invalidate({ preserveNavigation = false }: PermissionRefreshOptions = {}) {
    epoch++
    permissions.value = []
    if (!preserveNavigation) navigationPermissions.value = []
    loadedScope.value = ''
    loading.value = false
    failed.value = false
    revision.value++
  }
  async function load(options?: PermissionRefreshOptions) {
    invalidate(options)
    if (!hasEntry.value || !auth.effectiveTenantId || !auth.user?.id) return
    const current = epoch, requested = scope.value
    loading.value = true
    try {
      const apis = await fetchConnectionPermissions(String(auth.effectiveTenantId))
      if (current !== epoch || requested !== scope.value || !hasEntry.value) return
      permissions.value = apis
      navigationPermissions.value = apis
      loadedScope.value = requested
    } catch {
      if (current === epoch) {
        navigationPermissions.value = []
        failed.value = true
      }
    }
    finally { if (current === epoch) loading.value = false }
  }
  watch([scope, hasEntry], () => invalidate(), { flush: 'sync' })
  function can(permission: string): boolean { return ready.value && permissions.value.includes(permission) }
  /** 仅用于绘制侧栏，点击链接仍须通过路由校验。 */
  function hasNavigationPermission(permission: string): boolean { return hasEntry.value && navigationPermissions.value.includes(permission) }
  return { permissions, loading, failed, ready, revision, can, hasNavigationPermission, invalidate, load }
})
