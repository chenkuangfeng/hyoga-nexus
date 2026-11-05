/**
 * Nexus hooks for WeKnora chat components reused on the platform chat page.
 *
 * The Nexus chat page provides these actions; reused WeKnora components (`ToolApprovalCard`, `AskUserCard`,
 * `AgentStreamDisplay`, `botmsg`) check for them first and fall back to their WeKnora behaviour only when no
 * provider exists (the copied WeKnora views). This keeps one copy of each component while ensuring the
 * Nexus page never calls WeKnora endpoints (openspec 2026-11-04-weknora-chat-dialog, scope change 2026-11-05).
 */
import { inject, provide, type InjectionKey } from 'vue'

export interface NexusChatActions {
  /** Approve or reject a pending tool call; `pendingId` is the Nexus approval id. */
  resolveApproval(pendingId: string, decision: 'approve' | 'reject', args?: Record<string, unknown>): Promise<void>
  /** Answer the Run's question; `response` is WeKnora's ask_user answer object. */
  answerPrompt(pendingId: string, response: Record<string, unknown>): Promise<void>
  /** A WeKnora entry whose backend Nexus does not have yet: show the "not available yet" notice. */
  planned(feature: string): void
}

const nexusChatActionsKey: InjectionKey<NexusChatActions> = Symbol('nexusChatActions')

export function provideNexusChatActions(actions: NexusChatActions): void {
  provide(nexusChatActionsKey, actions)
}

/** Null outside the Nexus chat page. */
export function useNexusChatActions(): NexusChatActions | null {
  return inject(nexusChatActionsKey, null)
}
