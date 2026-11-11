import { get, post, patch, del } from '@/utils/request'
import { useAuthStore } from '@/stores/auth'
import type { AssistantAccessLevel } from '@/api/assistant'
import { PlannedFeatureError } from './knowledge-base/nexusAdapter'
import {
  ok, toNexusCreateBody, toNexusUpdateBody, toWeKnoraAutomation, toWeKnoraRun, ruleFromTrigger,
} from './nexusAutomationAdapter'

// Shapes mirror internal/types/automation.go. Every endpoint works on the
// caller's own automations; the server derives the owner from the request.

export type AutomationTriggerType = 'cron' | 'once'
export type AutomationSessionMode = 'per_run' | 'persistent'
export type AutomationMisfirePolicy = 'skip' | 'run_once'
export type AutomationOverlapPolicy = 'skip' | 'queue'
export type AutomationRunStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'skipped'
  | 'needs_attention'
export type AutomationRunTrigger = 'schedule' | 'manual' | 'misfire'

export interface AutomationTrigger {
  type: AutomationTriggerType
  /** Five fields (minute first), six (seconds first) or a descriptor such as @daily. */
  expr?: string
  /** When a once trigger fires, RFC 3339. */
  at?: string
  /** IANA zone; empty means UTC. */
  timezone?: string
}

export interface AutomationLimits {
  /** Execution time of one run, not counting approval waits. 0 uses the default. */
  max_duration_minutes?: number
}

export interface Automation {
  id: string
  name: string
  description: string
  enabled: boolean
  model_id: string
  instruction: string
  trigger: AutomationTrigger
  session_mode: AutomationSessionMode
  persistent_session_id: string
  carry_last_result: boolean
  misfire_policy: AutomationMisfirePolicy
  overlap_policy: AutomationOverlapPolicy
  access_level: AssistantAccessLevel
  approval_timeout_minutes: number
  limits: AutomationLimits
  notify_on_success: boolean
  next_run_at: string | null
  last_run_at: string | null
  last_success_at: string | null
  last_run_status: AutomationRunStatus | ''
  active_run_status?: 'queued' | 'running' | 'awaiting_approval' | ''
  consecutive_failures: number
  paused_reason: string
  created_at: string
  updated_at: string
  // Nexus-only fields (openspec 2026-11-07-tool-expansion 8.2a): the pinned agent, task state and owner.
  agent_id?: string | null
  agent_name?: string
  agent_version?: number | null
  /** `active`, `paused` (by the owner or a space admin) or `suspended` (by the scheduler; `paused_reason` says why). */
  state?: 'active' | 'paused' | 'suspended' | string
  run_count?: number
  owner_user_id?: string
  owner_name?: string
  session_id?: string
}

/** Fields of a create or update; on update a field left out is kept. */
export type AutomationInput = Partial<Pick<Automation,
  | 'agent_id'
  | 'name'
  | 'description'
  | 'model_id'
  | 'instruction'
  | 'trigger'
  | 'session_mode'
  | 'carry_last_result'
  | 'misfire_policy'
  | 'overlap_policy'
  | 'access_level'
  | 'approval_timeout_minutes'
  | 'limits'
  | 'notify_on_success'
>>

export interface AutomationRun {
  id: string
  automation_id: string
  scheduled_at: string
  trigger_kind: AutomationRunTrigger
  status: AutomationRunStatus
  session_id: string
  user_message_id: string
  assistant_message_id: string
  pending_prompt_id: string
  cancel_requested: boolean
  answer: string
  error: string
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface AutomationGrant {
  id: string
  grant_key: string
  label: string
  risk: string
  prompt_id: string
  created_at: string
  last_used_at: string | null
  /** Why the grant no longer applies, e.g. the agent changed. Empty while it does. */
  lapse?: string
}

export interface AutomationGrantCandidate {
  prompt_id: string
  grant_key: string
  label: string
  risk: string
  tool: string
  service_name?: string
  asked_at: string
}

/** `/api/v1/tenants/{effective tenant}/schedules`: scheduled tasks of the Nexus platform. */
function schedulesPath(): string {
  const tenantId = useAuthStore().effectiveTenantId || ''
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}/schedules`
}

const enc = encodeURIComponent

/** Rejects, without sending a request, for WeKnora features Nexus scheduling does not have. */
function planned(feature: string): Promise<never> {
  return Promise.reject(new PlannedFeatureError(feature, null))
}

/** Own tasks; a space owner or admin can ask for `all` to see everyone's. */
export async function listAutomations(scope: 'mine' | 'all' = 'mine') {
  const res: any = await get(`${schedulesPath()}?scope=${scope}`)
  return ok((res.items || []).map(toWeKnoraAutomation)) as { success: boolean; data: Automation[] }
}

export async function getAutomation(id: string) {
  return ok(toWeKnoraAutomation(await get(`${schedulesPath()}/${enc(id)}`))) as { success: boolean; data: Automation }
}

/** The task whose own session is `sessionId` (the page opens a task from its conversation). */
export async function getAutomationBySession(sessionId: string) {
  const res: any = await get(`${schedulesPath()}?scope=mine`)
  const found = (res.items || []).find((job: any) => job.session_id === sessionId)
  if (!found) throw new Error('Scheduled task not found')
  return ok(toWeKnoraAutomation(found)) as { success: boolean; data: Automation }
}

export async function createAutomation(input: AutomationInput) {
  return ok(toWeKnoraAutomation(await post(schedulesPath(), toNexusCreateBody(input)))) as { success: boolean; data: Automation }
}

export async function updateAutomation(id: string, input: AutomationInput) {
  return ok(toWeKnoraAutomation(await patch(`${schedulesPath()}/${enc(id)}`, toNexusUpdateBody(input)))) as { success: boolean; data: Automation }
}

export async function deleteAutomation(id: string) {
  await del(`${schedulesPath()}/${enc(id)}`)
  return ok(null) as { success: boolean }
}

/** The owner or a space admin may pause. */
export async function pauseAutomation(id: string) {
  return ok(toWeKnoraAutomation(await post(`${schedulesPath()}/${enc(id)}/pause`, {}))) as { success: boolean; data: Automation }
}

/** Schedule again from now; missed runs are not caught up. Only the owner can resume. */
export async function resumeAutomation(id: string) {
  return ok(toWeKnoraAutomation(await post(`${schedulesPath()}/${enc(id)}/resume`, {}))) as { success: boolean; data: Automation }
}

/** Start one run now (the schedule is unchanged); the answer is the run just started. */
export async function runAutomationNow(id: string) {
  const job: any = await post(`${schedulesPath()}/${enc(id)}/run`, {})
  const run = { id: job.last_run_id, session_id: job.session_id, status: 'queued', created_at: job.last_run_at }
  return ok(toWeKnoraRun(run, id)) as { success: boolean; data: AutomationRun }
}

/** The next fire times of a trigger in UTC; rejects an invalid or too frequent trigger. */
export async function validateAutomationTrigger(trigger: AutomationTrigger) {
  const rule = ruleFromTrigger(trigger)
  const res: any = await post(`${schedulesPath()}/preview`, { schedule: rule, timezone: trigger.timezone || 'UTC', count: 3 })
  return ok({ next_runs: res.times || [] }) as { success: boolean; data: { next_runs: string[] } }
}

/** Runs of the task's session, newest first. */
export async function listAutomationRuns(id: string, page = 1, pageSize = 20) {
  const res: any = await get(`${schedulesPath()}/${enc(id)}/runs?limit=${Math.min(50, page * pageSize)}`)
  const all = (res.items || []).map((run: any) => toWeKnoraRun(run, id))
  return ok(all.slice((page - 1) * pageSize, page * pageSize), { total: all.length }) as
    { success: boolean; data: AutomationRun[]; total: number }
}

/** Cancels a run through the platform's run cancellation. */
export async function cancelAutomationRun(runId: string) {
  const tenantId = useAuthStore().effectiveTenantId || ''
  await post(`/api/v1/tenants/${encodeURIComponent(tenantId)}/runs/${enc(runId)}/cancel`, {})
  return ok({ id: runId } as AutomationRun) as { success: boolean; data: AutomationRun }
}

// Scheduled runs are unattended in Nexus: they get no approval prompts, so there is nothing to grant.
export function listAutomationGrants(_id: string) {
  return Promise.resolve(ok([] as AutomationGrant[]))
}

export function listAutomationGrantCandidates(_id: string) {
  return Promise.resolve(ok([] as AutomationGrantCandidate[]))
}

export function addAutomationGrant(_id: string, _promptId: string) {
  return planned('自动化授权') as Promise<{ success: boolean; data: AutomationGrant }>
}

export function revokeAutomationGrant(_grantId: string) {
  return planned('自动化授权') as Promise<{ success: boolean }>
}

// ---------------------------------------------------------------------------
// In-app notifications.
// ---------------------------------------------------------------------------

export type NotificationKind =
  | 'automation.succeeded'
  | 'automation.failed'
  | 'automation.awaiting_approval'
  | 'automation.paused'

export interface AppNotification {
  id: string
  kind: NotificationKind | string
  title: string
  body: string
  /** In-app route the notification opens. */
  link: string
  source_type: string
  source_id: string
  read_at: string | null
  created_at: string
}

export interface PendingNotification {
  id: string
  title: string
  kind: string
  link: string
  created_at: string
}

export interface NotificationPage {
  items: AppNotification[]
  pending: PendingNotification[]
  unread: number
  read_count: number
  next_cursor: string
}

// Nexus has no in-app notification centre yet (design 8.2a, "不做"): the list is empty and marking is a no-op.
export function listNotifications(_limit = 20, _cursor = '') {
  const page: NotificationPage = { items: [], pending: [], unread: 0, read_count: 0, next_cursor: '' }
  return Promise.resolve(ok(page))
}

export function clearReadNotifications() {
  return Promise.resolve({ success: true })
}

export function markNotificationsRead(_ids: string[] = []) {
  return Promise.resolve({ success: true })
}
