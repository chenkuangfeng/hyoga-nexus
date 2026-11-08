/** Pure helpers of the "my skills" dialog (openspec 2026-11-07-skill-evolution, S4). */
import type { MySkill } from '@/api/nexus-agents'

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
