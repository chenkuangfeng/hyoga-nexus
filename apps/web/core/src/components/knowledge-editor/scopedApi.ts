/** 子面板的异步链在目标或身份失效后不能继续请求；不修改公共 API 的授权语义。 */
import { onBeforeUnmount } from 'vue'
import { useKnowledgeEditorHost } from './host'
export function useScopedApi<T extends object>(api: T): T {
  const host = useKnowledgeEditorHost(), scope = host.scopeKey?.()
  let disposed = false
  onBeforeUnmount(() => { disposed = true })
  const check = () => { if (disposed || host.scopeKey?.() !== scope || host.isCurrent?.() === false) throw new Error('knowledge_editor_scope_expired') }
  return new Proxy(api, {
    get(target, key, receiver) {
      const value: unknown = Reflect.get(target, key, receiver)
      if (typeof value !== 'function') return value
      return async (...args: unknown[]) => {
        check()
        const result: unknown = await Reflect.apply(value, undefined, args)
        check()
        return result
      }
    },
  })
}
