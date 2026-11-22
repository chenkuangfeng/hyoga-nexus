import { ref, watch } from 'vue'

const preferenceKey = 'nexus.kb.docs.viewMode'
type DocumentViewMode = 'list' | 'grid'

/** Restore the document layout preference shared by both applications on the same origin. */
export function useDocumentViewMode() {
  const viewMode = ref<DocumentViewMode>('list')
  try {
    if (localStorage.getItem(preferenceKey) === 'grid') viewMode.value = 'grid'
  } catch {
    // Browsing still works when storage is unavailable.
  }
  watch(viewMode, value => {
    try { localStorage.setItem(preferenceKey, value) } catch { /* Storage is optional. */ }
  })
  return viewMode
}
