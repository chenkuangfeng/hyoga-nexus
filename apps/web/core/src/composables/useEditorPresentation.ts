import { computed, inject, onBeforeUnmount, ref, watch, useId, type InjectionKey, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { loadPreference, savePreference } from './preferenceStorage'
export type EditorMode = 'modal' | 'route' | 'drawer'
export const ADMIN_EDITOR_MODE: InjectionKey<Ref<EditorMode>> = Symbol('adminEditorMode')
/** 管理应用独立提供偏好，员工设置与嵌入会话不受影响。 */
export function useAdminEditorPreference() {
  const readMode = (): EditorMode => { const stored = loadPreference('admin_editor_mode'); return stored === 'route' || stored === 'drawer' ? stored : 'modal' }
  const mode = ref<EditorMode>(readMode())
  const auth = useAuthStore()
  watch(() => auth.user?.id, () => { mode.value = readMode() })
  watch(mode, value => savePreference('admin_editor_mode', value))
  return mode
}
/** 替换路由编辑使用查询参数保存导航位置；返回时发出关闭请求，不重复提交表单。 */
export function useEditorPresentation(visible: () => boolean, close: () => void) {
  const preference = inject(ADMIN_EDITOR_MODE, undefined)
  const mode = computed(() => preference?.value)
  if (!preference) return { mode }
  const route = useRoute(), router = useRouter()
  const routeKey = `edit-${useId()}`
  let ownsRoute = false, disposed = false, editorPath = ''
  const clearRoute = () => {
    // 只清理本编辑器登记的位置，迟到的导航不能关闭后来打开的表单。
    if (route.path !== editorPath || route.query.editor !== routeKey) return
    const query = { ...route.query }; delete query.editor
    void router.replace({ path: editorPath, query })
  }
  watch(visible, open => {
    if (open && mode.value === 'route' && !route.query.editor) {
      ownsRoute = true; editorPath = route.path
      void router.push({ query: { ...route.query, editor: routeKey } }).then(() => {
        if (disposed || !visible()) clearRoute()
      })
    } else if (!open && ownsRoute) {
      ownsRoute = false; clearRoute()
    }
  }, { immediate: true })
  watch(() => route.query.editor, value => {
    if (ownsRoute && value !== routeKey) { ownsRoute = false; if (visible()) close() }
  })
  onBeforeUnmount(() => {
    disposed = true
    if (ownsRoute) { ownsRoute = false; clearRoute() }
  })
  return { mode }
}
