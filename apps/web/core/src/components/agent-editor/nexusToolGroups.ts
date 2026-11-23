/**
 * Tool group switches of the agent editor (openspec 2026-11-07-tool-expansion, R1, task 1.6).
 *
 * A group reaches a Run only when two layers agree: the deployment says it is *available* (`GET /agent-tools`
 * `group_info[].available`) and the agent has it *enabled* (`budgets.behavior.tool_groups_enabled`, falling back to the
 * group's `default_enabled`). The agent stores only the switches the user changed away from the default, so a group
 * added later keeps its own default for agents saved before it existed. Pure functions, no request helpers.
 */
import type { AgentToolGroupInfo } from '@nexus-web/core/api/nexus-agents'

/** Explicit per-group choices of one agent: group id -> on / off. */
export type GroupSwitches = Record<string, boolean>

/** The state a group is shown in; `locked` and `planned` groups cannot be switched. */
export type GroupStatus = 'locked' | 'planned' | 'unavailable' | 'off' | 'on'

/** Switch values from a stored `tool_groups_enabled`; anything that is not a boolean is dropped. */
export function switchesOf(value: unknown): GroupSwitches {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {}
  const result: GroupSwitches = {}
  for (const [key, flag] of Object.entries(value as Record<string, unknown>)) {
    if (typeof flag === 'boolean') result[key] = flag
  }
  return result
}

/** Whether the agent has the group on: the base group is always on, otherwise the choice or the default. */
export function groupEnabled(info: AgentToolGroupInfo, switches: GroupSwitches): boolean {
  if (info.locked) return true
  return switches[info.id] ?? info.default_enabled
}

/** The switches after the user set `info` to `value`; a value equal to the default removes the explicit choice. */
export function withGroupSwitch(switches: GroupSwitches, info: AgentToolGroupInfo, value: boolean): GroupSwitches {
  const next = { ...switches }
  if (value === info.default_enabled) delete next[info.id]
  else next[info.id] = value
  return next
}

/** How to present a group. A group still waiting for its tools (`planned` and no tools) is not switchable. */
export function groupStatus(info: AgentToolGroupInfo, switches: GroupSwitches): GroupStatus {
  if (info.locked) return 'locked'
  if (info.planned && info.tool_count === 0) return 'planned'
  if (!info.available) return 'unavailable'
  return groupEnabled(info, switches) ? 'on' : 'off'
}

const REASON_KEYS: Record<string, string> = {
  sandbox_disabled: 'reasonSandboxDisabled',
  sandbox_not_accepted: 'reasonNotAccepted',
  sandbox_local_not_allowed: 'reasonLocalNotAllowed',
  sandbox_profile_unknown: 'reasonUnknown',
  sandbox_connection_required: 'reasonConnection', sandbox_profile_paused: 'reasonPaused', sandbox_ssh_not_allowed: 'reasonSshNotAllowed',
  sandbox_required: 'reasonSandboxRequired',
  web_disabled: 'reasonWebDisabled',
  wiki_base_not_bound: 'reasonWikiNotBound',
}

/** The i18n key suffix (under `nexusAgent.groupReason`) for a stable reason code; unknown codes map to `reasonOther`. */
export function groupReasonKey(reason: string): string {
  return REASON_KEYS[reason] || 'reasonOther'
}
