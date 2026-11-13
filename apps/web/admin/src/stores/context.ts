/** 管理端当前企业权限。身份变化同步失效，权限只从服务端读取，不持久化或根据角色推断。 */
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { fetchConnectionPermissions } from '@nexus-web/core/api/enterprise-connections'

export const useAdminContext = defineStore('admin-context', () => {
  const auth = useAuthStore()
  const scope = computed(() => JSON.stringify([auth.user?.id || '', String(auth.effectiveTenantId || '')]))
  const hasEntry = computed(() => auth.currentEntries.includes('admin'))
  const permissions = ref<string[]>([]), loading = ref(false), failed = ref(false)
  const loadedScope = ref(''), revision = ref(0)
  let epoch = 0
  const ready = computed(() => hasEntry.value && !!loadedScope.value && loadedScope.value === scope.value)
  /** 在请求前及身份切换时立即清空旧企业权限，使旧确认弹窗和表单失效。 */
  function invalidate() { epoch++; permissions.value = []; loadedScope.value = ''; loading.value = false; failed.value = false; revision.value++ }
  async function load() {
    invalidate()
    if (!hasEntry.value || !auth.effectiveTenantId || !auth.user?.id) return
    const current = epoch, requested = scope.value
    loading.value = true
    try {
      const apis = await fetchConnectionPermissions(String(auth.effectiveTenantId))
      if (current !== epoch || requested !== scope.value || !hasEntry.value) return
      permissions.value = apis; loadedScope.value = requested
    } catch { if (current === epoch) failed.value = true }
    finally { if (current === epoch) loading.value = false }
  }
  watch([scope, hasEntry], invalidate, { flush: 'sync' })
  function can(permission: string): boolean { return ready.value && permissions.value.includes(permission) }
  return { permissions, loading, failed, ready, revision, can, invalidate, load }
})
