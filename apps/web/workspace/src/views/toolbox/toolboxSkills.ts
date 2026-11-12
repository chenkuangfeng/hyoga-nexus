/** Pure helpers of the toolbox skill table (openspec 2026-11-08-toolbox). */
import type { TenantSkill } from '@nexus-web/core/api/nexus-agents'

export type SkillRowBadge = 'builtin' | 'disabled' | 'hidden' | 'host' | 'unavailable' | 'caution' | 'dangerous' | 'rescan'

/** Badges for one library row. A badge is always a word, never colour alone. */
export function rowBadges(skill: TenantSkill): SkillRowBadge[] {
  const badges: SkillRowBadge[] = []
  if (skill.scope === 'builtin') badges.push('builtin')
  if (skill.disabled) badges.push('disabled')
  if (!skill.version_id) badges.push('unavailable')
  if (!skill.model_invocable) badges.push('hidden')
  if (skill.execution === 'local') badges.push('host')
  if (skill.verdict === 'caution') badges.push('caution')
  if (skill.verdict === 'dangerous') badges.push('dangerous')
  if (skill.rescan_needed) badges.push('rescan')
  return badges
}

export type RunState = { kind: 'none' } | { kind: 'ok' } | { kind: 'blocked', reason: string }

/** Whether a skill's scripts can run on the default sandbox profile: `none` for a skill without scripts. */
export function runState(skill: TenantSkill): RunState {
  if (!skill.run) return { kind: 'none' }
  return skill.run.ok ? { kind: 'ok' } : { kind: 'blocked', reason: skill.run.reason }
}

/** Library order: the space's own skills first, then builtin ones, each by name. */
export function sortLibrary(skills: readonly TenantSkill[]): TenantSkill[] {
  return [...skills].sort((a, b) => (a.scope === b.scope ? 0 : a.scope === 'space' ? -1 : 1) || a.name.localeCompare(b.name))
}

/** A file name for a downloaded skill zip. */
export function bundleFileName(name: string, version?: number): string {
  return `${name}${version ? `-v${version}` : ''}.zip`
}

const REASON_KEYS: Record<string, string> = {
  sandbox_disabled: 'reasonSandboxDisabled', sandbox_not_accepted: 'reasonNotAccepted',
  sandbox_local_not_allowed: 'reasonLocalNotAllowed', sandbox_profile_unknown: 'reasonUnknown',
  sandbox_unavailable: 'reasonUnavailable', local_not_allowed: 'reasonSkillLocal',
  skill_execution_not_permitted: 'reasonSkillLocal',
}

/** The agent editor's sandbox-profile message that explains a "scripts cannot run" reason code. */
export function runReasonKey(reason: string): string {
  return `nexusAgent.sandboxProfile.${REASON_KEYS[reason] ?? 'reasonOther'}`
}
