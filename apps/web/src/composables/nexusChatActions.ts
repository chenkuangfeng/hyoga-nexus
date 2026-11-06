/**
 * Nexus hooks for WeKnora chat components reused on the platform chat page.
 *
 * The Nexus chat page provides these actions; reused WeKnora components (`ToolApprovalCard`, `AskUserCard`,
 * `AgentStreamDisplay`, `botmsg`) check for them first and fall back to their WeKnora behaviour only when no
 * provider exists (the copied WeKnora views). This keeps one copy of each component while ensuring the
 * Nexus page never calls WeKnora endpoints (openspec 2026-11-04-weknora-chat-dialog, scope change 2026-11-05).
 */
import { inject, provide, type InjectionKey } from 'vue'

/** One entry of the composer's agent picker (`NexusAgentSelector`); `id` is the published version id. */
export interface NexusAgentOption {
  id: string
  name: string
  description: string
}

export interface NexusChatActions {
  /**
   * Approve or reject a pending tool call; `pendingId` is the Nexus approval id. `rememberForSession` also
   * allows later calls of the tool in this session (openspec 2026-11-06-tool-call-hardening E).
   */
  resolveApproval(pendingId: string, decision: 'approve' | 'reject', args?: Record<string, unknown>,
    rememberForSession?: boolean): Promise<void>
  /** Answer the Run's question; `response` is WeKnora's ask_user answer object. */
  answerPrompt(pendingId: string, response: Record<string, unknown>): Promise<void>
  /** A WeKnora entry whose backend Nexus does not have yet: show the "not available yet" notice. */
  planned(feature: string): void
  /**
   * Publish or reject a memory draft the model proposed (openspec 2026-11-06-memory-evolution E1).
   * Resolves `handled` when the draft was already reviewed elsewhere (HTTP 409).
   */
  reviewMemoryDraft(draftId: string, approve: boolean, title: string): Promise<'published' | 'rejected' | 'handled'>
  /** Whether a draft still awaits review; null when the state cannot be read. */
  isMemoryDraftPending(draftId: string): Promise<boolean | null>
  /** Archive a published memory from the "used memories" row (it leaves future conversations). */
  forgetMemory(entryId: string): Promise<void>
}

const nexusChatActionsKey: InjectionKey<NexusChatActions> = Symbol('nexusChatActions')

export function provideNexusChatActions(actions: NexusChatActions): void {
  provide(nexusChatActionsKey, actions)
}

/** Null outside the Nexus chat page. */
export function useNexusChatActions(): NexusChatActions | null {
  return inject(nexusChatActionsKey, null)
}
