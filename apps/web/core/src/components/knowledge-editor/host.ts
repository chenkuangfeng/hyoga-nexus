/** 编辑器只发出设置导航请求；具体应用决定打开面板还是提示当前入口不可用。 */
import { inject, type InjectionKey } from 'vue'
export interface KnowledgeEditorHost {
  scopeKey?(): string
  isCurrent?(): boolean
  openSettings(section: string, tab?: string): void
  closeKBEditor(): void
  readonly showSettingsModal: boolean
  readonly kbEditorInitialSection: string
}
export const KNOWLEDGE_EDITOR_HOST: InjectionKey<KnowledgeEditorHost> = Symbol('knowledge-editor-host')
export function useKnowledgeEditorHost(): KnowledgeEditorHost {
  return inject(KNOWLEDGE_EDITOR_HOST, { openSettings() {}, closeKBEditor() {}, showSettingsModal: false, kbEditorInitialSection: '' })
}
