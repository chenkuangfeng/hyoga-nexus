/** Pure helpers of the toolbox tool catalog (openspec 2026-11-08-toolbox). */
import type { AgentToolEntry } from '@/api/nexus-agents'

export type ToolState = 'available' | 'disabled' | 'notEnabled'

/** `disabled`: a builtin tool this space switched off; `notEnabled`: a non-builtin tool the space has not enabled. */
export function toolState(tool: AgentToolEntry): ToolState {
  if (tool.disabled) return 'disabled'
  return tool.enabled_in_tenant ? 'available' : 'notEnabled'
}

/** What an administrator can do with a tool: switch a builtin one off or back on, or enable one the space lacks. */
export function toolAction(tool: AgentToolEntry): 'disable' | 'restore' | 'enable' | null {
  if (tool.builtin) return tool.disabled ? 'restore' : 'disable'
  return tool.enabled_in_tenant ? null : 'enable'
}

export interface ToolSection { key: string, tools: AgentToolEntry[] }

/** Tools grouped in the catalog's group order; empty groups are left out. */
export function groupTools(tools: readonly AgentToolEntry[], order: readonly string[]): ToolSection[] {
  const keys = [...order, ...tools.map((tool) => tool.group).filter((group) => !order.includes(group))]
  return [...new Set(keys)].map((key) => ({ key, tools: tools.filter((tool) => tool.group === key) }))
    .filter((section) => section.tools.length > 0)
}
