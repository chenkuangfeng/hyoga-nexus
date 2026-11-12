/**
 * Adapter between Nexus scheduled tasks and the WeKnora automation shapes the copied pages read
 * (openspec 2026-11-07-tool-expansion 8.2a, tasks 10.3/10.4).
 *
 * Nexus keeps scheduling deliberately small: a task is owned by one person, pinned to one published agent version,
 * runs in its own session and fires by one of three rules — every N minutes, daily at a time, weekly on one day. The
 * WeKnora page speaks cron expressions, so a trigger converts only when it expresses one of those three rules
 * exactly; anything else rejects with {@link PlannedFeatureError} and the page shows "待实现" instead of sending it.
 *
 * Mapping of the rules to triggers:
 *   interval N minutes      <-> `@every Nm`                 (cron descriptor)
 *   daily at HH:MM          <-> `M H * * *`
 *   weekly on a day at time <-> `M H * * D`   with cron D (0 = Sunday); Nexus counts 0 = Monday
 *
 * Pure functions with type-only imports, so they are unit tested directly.
 */
import type { Automation, AutomationRun, AutomationRunStatus, AutomationTrigger } from './automation'
import { PlannedFeatureError } from './knowledge-base/nexusAdapter'

type Json = Record<string, any>

const EVERY = /^@every (\d+)([mh])$/
const TIME = /^(\d{1,2}) (\d{1,2}) \* \* (\*|[0-6])$/

/** The "待实现" rejection for a trigger the Nexus scheduler cannot express. */
export function unsupportedTrigger(): PlannedFeatureError {
  return new PlannedFeatureError('该触发方式（目前支持每 N 分钟、每天、每周某一天）', null)
}

/** The Nexus rule of a WeKnora trigger; throws {@link PlannedFeatureError} when it has no exact equivalent. */
export function ruleFromTrigger(trigger: AutomationTrigger | undefined): Json {
  if (!trigger || trigger.type !== 'cron') throw unsupportedTrigger()
  const expr = (trigger.expr || '').trim()
  const every = EVERY.exec(expr)
  if (every) return { kind: 'interval', every_minutes: Number(every[1]) * (every[2] === 'h' ? 60 : 1) }
  const timed = TIME.exec(expr)
  if (!timed) throw unsupportedTrigger()
  const [, minute, hour, dow] = timed
  const at = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`
  if (dow === '*') return { kind: 'daily', at }
  return { kind: 'weekly', weekday: (Number(dow) + 6) % 7, at }
}

/** The WeKnora trigger of a Nexus rule. */
export function triggerFromRule(rule: Json | undefined, timezone: string): AutomationTrigger {
  const tz = timezone || 'UTC'
  if (!rule || typeof rule !== 'object') return { type: 'cron', expr: '', timezone: tz }
  if (rule.kind === 'interval') return { type: 'cron', expr: `@every ${Number(rule.every_minutes)}m`, timezone: tz }
  const [hour, minute] = String(rule.at || '00:00').split(':').map(part => Number(part))
  if (rule.kind === 'weekly') {
    return { type: 'cron', expr: `${minute} ${hour} * * ${(Number(rule.weekday) + 1) % 7}`, timezone: tz }
  }
  return { type: 'cron', expr: `${minute} ${hour} * * *`, timezone: tz }
}

/** A Nexus task (`GET /schedules`) in the WeKnora automation shape, plus the Nexus-only fields the page shows. */
export function toWeKnoraAutomation(job: Json): Automation & Json {
  const state = String(job.state || 'active')
  return {
    id: String(job.id),
    name: String(job.name || ''),
    description: '',
    enabled: state === 'active',
    model_id: '',
    instruction: String(job.prompt || ''),
    trigger: triggerFromRule(job.rule, String(job.timezone || 'UTC')),
    session_mode: 'persistent',
    persistent_session_id: String(job.session_id || ''),
    carry_last_result: false,
    misfire_policy: 'skip',
    overlap_policy: 'skip',
    access_level: 'confirm',
    approval_timeout_minutes: 0,
    limits: {},
    notify_on_success: false,
    next_run_at: job.next_run_at ?? null,
    last_run_at: job.last_run_at ?? null,
    last_success_at: null,
    last_run_status: '',
    consecutive_failures: 0,
    paused_reason: state === 'suspended' ? String(job.last_error || 'suspended') : '',
    created_at: String(job.created_at || ''),
    updated_at: String(job.created_at || ''),
    // Nexus-only fields.
    agent_id: job.agent_id ?? null,
    agent_name: String(job.agent_name || ''),
    agent_version: job.agent_version ?? null,
    state,
    run_count: Number(job.run_count || 0),
    owner_user_id: String(job.owner_user_id || ''),
    owner_name: String(job.owner_name || ''),
    session_id: String(job.session_id || ''),
  }
}

/** Body of `POST /schedules`; the agent comes from the page's `agent_id` (the editor's agent selector). */
export function toNexusCreateBody(input: Json) {
  const trigger = input.trigger as AutomationTrigger | undefined
  return {
    name: String(input.name || '').trim(),
    prompt: String(input.instruction || ''),
    agent_id: input.agent_id,
    schedule: ruleFromTrigger(trigger),
    timezone: trigger?.timezone || 'UTC',
  }
}

/** Body of `PATCH /schedules/{id}`; fields the page left out are left out (the server keeps them). */
export function toNexusUpdateBody(input: Json) {
  const body: Json = {}
  if (input.name !== undefined) body.name = String(input.name).trim()
  if (input.instruction !== undefined) body.prompt = String(input.instruction)
  if (input.trigger !== undefined) {
    body.schedule = ruleFromTrigger(input.trigger)
    body.timezone = input.trigger.timezone || 'UTC'
  }
  return body
}

const RUN_STATUS: Record<string, AutomationRunStatus> = {
  queued: 'queued', running: 'running', waiting_approval: 'awaiting_approval', waiting_input: 'needs_attention',
  completed: 'succeeded', failed: 'failed', cancelled: 'cancelled', interrupted: 'failed',
}

/** One Run of the task's session as a WeKnora automation run. */
export function toWeKnoraRun(run: Json, automationId: string): AutomationRun {
  return {
    id: String(run.id),
    automation_id: automationId,
    scheduled_at: String(run.created_at || ''),
    trigger_kind: 'schedule',
    status: RUN_STATUS[String(run.status)] ?? 'failed',
    session_id: String(run.session_id || ''),
    user_message_id: '',
    assistant_message_id: '',
    pending_prompt_id: '',
    cancel_requested: Boolean(run.cancel_requested),
    answer: '',
    error: String(run.error_code || ''),
    started_at: run.started_at ?? null,
    finished_at: run.ended_at ?? null,
    created_at: String(run.created_at || ''),
  }
}

/** The envelope the pages read. */
export function ok<T>(data: T, extra: Json = {}): { success: true, data: T } & Json {
  return { success: true, data, ...extra }
}
