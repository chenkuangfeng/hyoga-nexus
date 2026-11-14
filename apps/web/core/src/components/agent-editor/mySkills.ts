/** Pure helpers of the "my skills" dialog (openspec 2026-11-07-skill-evolution, S4). */
import type { MySkill } from '@nexus-web/core/api/nexus-agents'

export type SkillBadge = 'archived' | 'superseded' | 'installing' | 'buildFailed' | 'hiddenFromModel' | 'caution'

/** The status badges one private skill shows, most important first. A badge is a statement, never colour alone. */
export function skillBadges(skill: MySkill): SkillBadge[] {
  const badges: SkillBadge[] = []
  if (skill.archived) badges.push('archived')
  if (skill.superseded) badges.push('superseded')
  if (skill.latest_state === 'installing') badges.push('installing')
  if (skill.latest_state === 'failed') badges.push('buildFailed')
  if (!skill.model_invocable) badges.push('hiddenFromModel')
  if (skill.verdict === 'caution') badges.push('caution')
  return badges
}

/** Whether the skill is offered to the owner's conversations right now. */
export function isOffered(skill: MySkill): boolean {
  return !skill.archived && !skill.superseded && skill.version !== null && skill.model_invocable
}

const SUBMISSION_ERRORS: Record<string, string> = {
  skill_name_taken_by_builtin: 'nameTaken', skill_name_taken_by_library: 'nameTaken',
  skill_submission_queue_full: 'limit', skill_submission_user_limit: 'limit', skill_submission_rate_limit: 'limit',
  skill_base_changed: 'stale', skill_submission_not_pending: 'notPending', skill_scan_refused: 'refused',
  skill_submission_reason_required: 'reason', skill_not_found: 'gone', skill_submission_not_found: 'gone',
}

/** The i18n key (under `nexusAgent.share.error`) for a sharing failure code; `other` when it is not known. */
export function submissionErrorKey(code: string): string {
  return `nexusAgent.share.error.${SUBMISSION_ERRORS[code] ?? 'other'}`
}

/** What the "share" button on a private skill does for this caller: administrators publish at once, holders of
 * `skills:submit` file a submission, everyone else cannot share. */
export function shareAction(apis: readonly string[]): 'share' | 'submit' | null {
  if (apis.includes('tools:manage')) return 'share'
  return apis.includes('skills:submit') ? 'submit' : null
}

/** "n times, last on …" for a skill, or null when there is nothing to say (builtin skills carry no numbers). */
export function usageText(count: number | null | undefined, last: string | null | undefined):
  { kind: 'never' } | { kind: 'used', count: number, when: string } | null {
  if (count === null || count === undefined) return null
  if (!last) return { kind: 'never' }
  return { kind: 'used', count, when: last.slice(0, 16).replace('T', ' ') }
}
