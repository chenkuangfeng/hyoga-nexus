import type { Automation, AutomationTrigger } from '@/api/automation'

// The editor offers a few schedule shapes and falls back to a raw cron
// expression for anything else. Cron here is the server's five-field form,
// minute first, evaluated in the trigger's timezone.

/** An elapsed one-shot schedule has no future occurrence to resume. */
export function hasEndedOnceSchedule(automation: Pick<Automation, 'enabled' | 'trigger'>, now = Date.now()): boolean {
  return !automation.enabled && automation.trigger.type === 'once'
    && Date.parse(automation.trigger.at || '') <= now
}

export type ScheduleKind = 'interval' | 'hourly' | 'daily' | 'weekdays' | 'weekly' | 'monthly' | 'once' | 'custom'

/**
 * Kinds the Nexus scheduler can run (design 8.2a): every N minutes, daily, and weekly on one day. The editor shows the
 * others as "待实现" and does not let them be chosen.
 */
export const SUPPORTED_KINDS: readonly ScheduleKind[] = ['interval', 'daily', 'weekly']

/** Shortest interval the scheduler accepts, in minutes (`MIN_INTERVAL_MINUTES` of the backend). */
export const MIN_INTERVAL_MINUTES = 15

export function isSupportedKind(kind: ScheduleKind): boolean {
  return SUPPORTED_KINDS.includes(kind)
}

export interface ScheduleForm {
  kind: ScheduleKind
  minute: number
  hour: number
  /** Days of the week for weekly, 0 = Sunday. */
  days: number[]
  /** Day of the month for monthly. */
  day: number
  /** Wall-clock time of a once trigger in the timezone, "YYYY-MM-DD HH:mm". */
  at: string
  /** Expression of a custom trigger. */
  expr: string
  /** Minutes between runs of an interval trigger. */
  every: number
}

export function defaultScheduleForm(): ScheduleForm {
  return { kind: 'daily', minute: 0, hour: 9, days: [1], day: 1, at: '', expr: '', every: 60 }
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export function timezoneOptions(current?: string): string[] {
  let zones: string[] = []
  try {
    zones = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? []
  } catch {
    zones = []
  }
  const set = new Set(zones.length ? zones : ['UTC', 'Asia/Shanghai', 'America/New_York', 'Europe/London'])
  set.add('UTC')
  if (current) set.add(current)
  return [...set]
}

const NUM = /^\d{1,2}$/

function num(field: string, min: number, max: number): number | null {
  if (!NUM.test(field)) return null
  const n = Number(field)
  return n >= min && n <= max ? n : null
}

/** Read a trigger back into the editor; anything the presets cannot express is custom. */
export function scheduleFormFromTrigger(trigger: AutomationTrigger | undefined): ScheduleForm {
  const form = defaultScheduleForm()
  if (!trigger) return form
  if (trigger.type === 'once') {
    form.kind = 'once'
    form.at = trigger.at ? zonedWallClock(trigger.at, trigger.timezone) : ''
    return form
  }
  const expr = (trigger.expr || '').trim()
  form.expr = expr
  form.kind = 'custom'
  const every = /^@every (\d+)([mh])$/.exec(expr)
  if (every) return { ...form, kind: 'interval', every: Number(every[1]) * (every[2] === 'h' ? 60 : 1) }
  const f = expr.split(/\s+/)
  if (f.length !== 5) return form
  const [mi, h, dom, mon, dow] = f
  const minute = num(mi, 0, 59)
  if (minute === null || mon !== '*') return form
  if (h === '*' && dom === '*' && dow === '*') {
    return { ...form, kind: 'hourly', minute }
  }
  const hour = num(h, 0, 23)
  if (hour === null) return form
  if (dom === '*' && dow === '*') return { ...form, kind: 'daily', minute, hour }
  if (dom === '*' && dow === '1-5') return { ...form, kind: 'weekdays', minute, hour }
  if (dom === '*' && /^[0-6](,[0-6])*$/.test(dow)) {
    const days = [...new Set(dow.split(',').map(Number))].sort((a, b) => a - b)
    return { ...form, kind: 'weekly', minute, hour, days }
  }
  const day = num(dom, 1, 31)
  if (day !== null && dow === '*') return { ...form, kind: 'monthly', minute, hour, day }
  return form
}

/** The trigger the editor describes, or null while it is incomplete. */
export function triggerFromScheduleForm(form: ScheduleForm, timezone: string): AutomationTrigger | null {
  const tz = timezone || 'UTC'
  const m = form.minute
  const h = form.hour
  let expr = ''
  switch (form.kind) {
    case 'interval':
      if (!Number.isInteger(form.every) || form.every < 1) return null
      expr = `@every ${form.every}m`
      break
    case 'hourly':
      expr = `${m} * * * *`
      break
    case 'daily':
      expr = `${m} ${h} * * *`
      break
    case 'weekdays':
      expr = `${m} ${h} * * 1-5`
      break
    case 'weekly':
      if (!form.days.length) return null
      expr = `${m} ${h} * * ${[...new Set(form.days)].sort((a, b) => a - b).join(',')}`
      break
    case 'monthly':
      expr = `${m} ${h} ${form.day} * *`
      break
    case 'custom':
      expr = form.expr.trim()
      if (!expr) return null
      break
    case 'once': {
      const at = wallClockToISO(form.at, tz)
      return at ? { type: 'once', at, timezone: tz } : null
    }
  }
  return { type: 'cron', expr, timezone: tz }
}

function zoneParts(date: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(date)
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0)
  return { y: get('year'), mo: get('month'), d: get('day'), h: get('hour') % 24, mi: get('minute'), s: get('second') }
}

function offsetMs(date: Date, timeZone: string): number {
  const p = zoneParts(date, timeZone)
  return Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s) - Math.floor(date.getTime() / 1000) * 1000
}

const WALL = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})$/

/** RFC 3339 instant of wall-clock time local in timeZone, or '' if local is malformed. */
export function wallClockToISO(local: string, timeZone: string): string {
  const match = WALL.exec(local || '')
  if (!match) return ''
  const [, y, mo, d, h, mi] = match.map(Number)
  const guess = Date.UTC(y, mo - 1, d, h, mi)
  try {
    let t = guess - offsetMs(new Date(guess), timeZone)
    // A second pass settles instants near a daylight-saving change.
    t = guess - offsetMs(new Date(t), timeZone)
    const date = new Date(t)
    const p = zoneParts(date, timeZone)
    // Date.UTC normalizes invalid fields, and offset iteration can land on a
    // different local time inside a DST gap. Never schedule that other time.
    if (p.y !== y || p.mo !== mo || p.d !== d || p.h !== h || p.mi !== mi || p.s !== 0) return ''
    return date.toISOString()
  } catch {
    return ''
  }
}

/** Wall-clock "YYYY-MM-DD HH:mm" of iso in timeZone. */
export function zonedWallClock(iso: string, timeZone?: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const p = zoneParts(date, timeZone || 'UTC')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${p.y}-${pad(p.mo)}-${pad(p.d)} ${pad(p.h)}:${pad(p.mi)}`
}

/** iso as a medium date and short time in timeZone. */
export function formatInZone(iso: string | null | undefined, timeZone: string | undefined, locale: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  try {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: timeZone || 'UTC' })
      .format(date)
  } catch {
    return date.toLocaleString(locale)
  }
}

export function weekdayName(day: number, locale: string): string {
  // 2023-01-01 was a Sunday.
  return new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2023, 0, 1 + day)))
}

type Translate = (key: string, params?: Record<string, unknown>) => string

/** A short sentence for when trigger runs, such as "Every day at 09:00". */
export function describeTrigger(trigger: AutomationTrigger, t: Translate, locale: string): string {
  const form = scheduleFormFromTrigger(trigger)
  const time = `${String(form.hour).padStart(2, '0')}:${String(form.minute).padStart(2, '0')}`
  switch (form.kind) {
    case 'interval':
      return t('automation.schedule.describe.everyMinutes', { n: form.every })
    case 'hourly':
      return t('automation.schedule.describe.hourly', { minute: String(form.minute).padStart(2, '0') })
    case 'daily':
      return t('automation.schedule.describe.daily', { time })
    case 'weekdays':
      return t('automation.schedule.describe.weekdays', { time })
    case 'weekly':
      return t('automation.schedule.describe.weekly', {
        days: form.days.map((d) => weekdayName(d, locale)).join(', '),
        time,
      })
    case 'monthly':
      return t('automation.schedule.describe.monthly', { day: form.day, time })
    case 'once':
      return t('automation.schedule.describe.once', { at: formatInZone(trigger.at, trigger.timezone, locale) })
    default: {
      const every = /^\*\/(\d+) \* \* \* \*$/.exec(form.expr.trim())
      if (every) return t('automation.schedule.describe.everyMinutes', { n: Number(every[1]) })
      const hours = /^0 \*\/(\d+) \* \* \*$/.exec(form.expr.trim())
      if (hours) return t('automation.schedule.describe.everyHours', { n: Number(hours[1]) })
      return t('automation.schedule.describe.custom', { expr: form.expr })
    }
  }
}
