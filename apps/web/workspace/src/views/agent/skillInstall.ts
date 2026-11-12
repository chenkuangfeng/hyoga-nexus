/**
 * Pure helpers of the skill install dialog (openspec 2026-11-07-skill-evolution, S3): what an install failure means
 * for the user, and which i18n key says it. No Vue, no network, so they are unit-testable.
 */

export interface ScanFinding { rule: string, severity: string, category: string, path: string, line: number | null, excerpt: string }

/** A failed install request, reduced to what the dialog needs. */
export interface InstallFailure {
  /** The stable server code, for example `bundle_invalid` or `skill_ack_required`. */
  code: string
  /** Text after the first colon of a code such as `skill_verify_failed:scripts/a.py:...`. */
  detail: string
  /** The scan stopped the install but an administrator may release it. */
  needsAck: boolean
  verdict: string
  findings: ScanFinding[]
  /** The server's own message, used when no label is known. */
  message: string
}

const GENERIC_CLASSES = new Set(['invalid_configuration', 'conflict', 'not_found', 'forbidden', 'invalid_request'])

/** Reduce the object the request layer rejects with (`{status, message, error: {code, message, details}}`). */
export function parseInstallFailure(error: unknown): InstallFailure {
  const record = (error && typeof error === 'object' ? error : {}) as Record<string, any>
  const body = (record.error && typeof record.error === 'object' ? record.error : {}) as Record<string, any>
  const classCode = typeof body.code === 'string' ? body.code : ''
  const message = typeof body.message === 'string' ? body.message : typeof record.message === 'string' ? record.message : ''
  // Rule-level problems arrive as a generic class with the stable code in the message; scan stops carry their own code.
  const full = !classCode || GENERIC_CLASSES.has(classCode) ? message : classCode
  const [code, ...rest] = full.split(':')
  const details = (body.details && typeof body.details === 'object' ? body.details : {}) as Record<string, any>
  return {
    code: code.trim(), detail: rest.join(':').trim(), needsAck: code === 'skill_ack_required',
    verdict: typeof details.verdict === 'string' ? details.verdict : '',
    findings: Array.isArray(details.findings) ? details.findings as ScanFinding[] : [], message,
  }
}

const GROUPS: Record<string, string[]> = {
  archive: ['bundle_invalid', 'bundle_encrypted', 'bundle_layout', 'bundle_skill_md_missing', 'bundle_skill_md_not_text',
    'bundle_skill_not_found', 'bundle_skill_ambiguous', 'frontmatter_missing', 'frontmatter_unterminated'],
  tooLarge: ['bundle_too_large', 'bundle_too_large_unpacked', 'bundle_too_many_entries', 'bundle_ratio_suspicious',
    'skill_file_too_large', 'skill_total_too_large', 'skill_too_many_files'],
  unsafe: ['bundle_symlink', 'skill_path_invalid', 'skill_path_duplicate'],
  sourceInvalid: ['skill_source_invalid'],
  sourceDenied: ['skill_source_denied'],
  sourceUnreachable: ['skill_source_unreachable', 'skill_source_timeout', 'skill_source_http_error'],
  confirm: ['skill_source_confirmation_required'],
  verify: ['skill_verify_failed'],
  blocked: ['skill_scan_blocked', 'skill_scan_refused', 'skill_review_required'],
  needsAck: ['skill_ack_required'],
  busy: ['skill_install_in_progress'],
  unchanged: ['skill_version_unchanged'],
  name: ['skill_name_taken_by_builtin', 'skill_source_conflict'],
}

/** The i18n key (under `nexusAgent.skillInstall.error`) that explains `code`; `other` when it is not known. */
export function failureKey(code: string): string {
  for (const [group, codes] of Object.entries(GROUPS)) if (codes.includes(code)) return `nexusAgent.skillInstall.error.${group}`
  return 'nexusAgent.skillInstall.error.other'
}

export const isFinishedBuild = (state: string): boolean => state === 'ready' || state === 'failed'

/** Whether `text` looks like a source the server accepts, so the button can wait for a plausible entry. */
export function looksLikeSource(text: string): boolean {
  const value = text.trim()
  return value.length > 0 && value.length <= 500 && !/\s/.test(value)
    && (value.startsWith('https://') || value.startsWith('github:') || value.startsWith('clawhub:'))
}
