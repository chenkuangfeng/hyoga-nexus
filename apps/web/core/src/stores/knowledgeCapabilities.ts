/**
 * Knowledge capability catalog of the active space (openspec 2026-11-06-knowledge-base K0, decision 5).
 *
 * Loaded once per space and shared by every knowledge page and settings section. Until the catalog loads,
 * or when it fails to load, everything reads as planned (fail closed): a planned control is only disabled,
 * never sent, so a missing catalog cannot cause requests to endpoints that do not exist.
 */
import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import {
  capabilityState, emptyCatalog, fetchCapabilities, groupItems, isAvailable,
  type CapabilityCatalog, type CapabilityGroup, type CapabilityItem, type CapabilityState,
} from '@nexus-web/core/api/nexus-knowledge'

export const useKnowledgeCapabilitiesStore = defineStore('knowledgeCapabilities', () => {
  const catalog = ref<CapabilityCatalog>(emptyCatalog())
  const loadedFor = ref('')
  const loadError = ref('')
  let pending: Promise<void> | null = null
  let epoch = 0

  async function ensureLoaded(force = false): Promise<void> {
    const tenantId = useAuthStore().effectiveTenantId || ''
    if (!tenantId) return
    if (!force && loadedFor.value === tenantId) return
    if (pending) return pending
    const current = epoch
    pending = (async () => {
      try {
        const result = await fetchCapabilities(tenantId)
        if (current !== epoch) return
        catalog.value = result
        loadedFor.value = tenantId
        loadError.value = ''
      } catch (error) {
        if (current !== epoch) return
        catalog.value = emptyCatalog()
        loadError.value = error instanceof Error ? error.message : String(error)
      } finally {
        if (current === epoch) pending = null
      }
    })()
    return pending
  }

  watch(() => [useAuthStore().effectiveTenantId, useAuthStore().user?.id], () => {
    epoch++; pending = null; loadedFor.value = ''; catalog.value = emptyCatalog(); loadError.value = ''
  }, { flush: 'sync' })

  return {
    catalog, loadError, ensureLoaded,
    available: (group: CapabilityGroup, key: string): boolean => isAvailable(catalog.value, group, key),
    state: (group: CapabilityGroup, key: string): CapabilityState => capabilityState(catalog.value, group, key),
    items: (group: CapabilityGroup): CapabilityItem[] => groupItems(catalog.value, group),
  }
})
