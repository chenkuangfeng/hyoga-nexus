import { computed, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useI18n } from 'vue-i18n'
import { deleteMemoryItem } from '@/api/memory'
import { useNexusChatActions } from '@/composables/nexusChatActions'

export type UsedMemory = { id: string; kind: string; content: string }

/**
 * State for the "memories used by this turn" timeline row.
 *
 * Both timelines (the quick-answer pipeline and the agent stream) show the same
 * row, so the recall list, the expand state and the forget call live here rather
 * than being written twice and drifting apart.
 */
export function useChatMemoryRow(getUsedMemories: () => UsedMemory[] | undefined) {
  const { t } = useI18n()
  // On the Nexus chat page "forget" archives the entry through the platform API (B5); the copied
  // WeKnora views keep WeKnora's delete endpoint.
  const nexusActions = useNexusChatActions()

  const expanded = ref(false)
  const forgettingId = ref('')
  const forgottenIds = ref<string[]>([])

  const memoryItems = computed(() => {
    const used = getUsedMemories()
    if (!Array.isArray(used)) return []
    return used.filter((memory) => memory?.id && !forgottenIds.value.includes(memory.id))
  })

  const hasMemory = computed(() => memoryItems.value.length > 0)

  const toggle = () => {
    expanded.value = !expanded.value
  }

  // Forgetting from the answer is the shortest path from noticing a wrong memory
  // to it being gone, which is where users actually notice one.
  const forget = async (memory: { id: string }) => {
    forgettingId.value = memory.id
    try {
      if (nexusActions) await nexusActions.forgetMemory(memory.id)
      else await deleteMemoryItem(memory.id)
      forgottenIds.value = [...forgottenIds.value, memory.id]
      MessagePlugin.success(t('chat.memoryForgotten'))
    } catch (error: any) {
      MessagePlugin.error(error?.message || t('chat.memoryForgetFailed'))
    } finally {
      forgettingId.value = ''
    }
  }

  return { memoryItems, hasMemory, expanded, forgettingId, toggle, forget }
}
