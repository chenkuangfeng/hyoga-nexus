import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useAuthStore } from '@nexus-web/core/stores/auth'

/** A new model's form, filled in by the tool; never carries credentials. */
export interface ModelFormDraft {
  type: 'chat' | 'embedding' | 'rerank' | 'vllm' | 'asr'
  source?: 'remote' | 'local'
  provider?: string
  model_name?: string
  display_name?: string
  base_url?: string
}

/** A new remote MCP service's form, filled in by the tool; never carries credentials. */
export interface McpServiceFormDraft {
  name: string
  usage_instructions?: string
  transport_type: 'sse' | 'http-streamable'
  url: string
  auth_type?: '' | 'api_key' | 'oauth'
  api_key_header?: string
}


export type PageDraft = { kind: 'model'; draft: ModelFormDraft } | { kind: 'mcp_service'; draft: McpServiceFormDraft }

/** 普通聊天工具卡片交给编辑器的一次性草稿，不持久化，也不携带凭据。 */
export const usePageDraftStore = defineStore('pageDrafts', () => {
  const auth = useAuthStore()
  const pageDraft = ref<PageDraft | null>(null)
  // 账号或企业切换时同步丢弃草稿；同身份的认证刷新不清空未完成编辑。
  watch(() => JSON.stringify([auth.user?.id, auth.effectiveTenantId]), () => { pageDraft.value = null }, { flush: 'sync' })
  /** 接收已校验、无凭据的工具结果草稿；传入 null 清空，不写入浏览器存储。 */
  const setPageDraft = (draft: PageDraft | null) => { pageDraft.value = draft }
  /** 取出并消费指定编辑器的草稿；类型不匹配时返回 null 并保留原草稿。 */
  function takePageDraft(kind: 'model'): ModelFormDraft | null
  function takePageDraft(kind: 'mcp_service'): McpServiceFormDraft | null
  function takePageDraft(kind: PageDraft['kind']) {
    if (pageDraft.value?.kind !== kind) return null
    const draft = pageDraft.value.draft
    pageDraft.value = null
    return draft
  }
  return { pageDraft, setPageDraft, takePageDraft }
})
