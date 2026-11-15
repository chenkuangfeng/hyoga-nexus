/** 企业技能投稿审核 API；技能正文、文件与扫描输出均按不可信纯文本校验。 */
import { get, post } from '../utils/request'

export interface SkillSubmissionRow { id: string; name: string; description: string; origin: string; state: string; verdict: string; findings: number; review_reason: string | null; created_at: string; updates_existing: boolean }
export interface SkillSubmissionFinding { rule: string; severity: string; path: string; line: number | null; excerpt: string }
export interface SkillSubmissionDetail extends SkillSubmissionRow { skill_md: string; files: Record<string, string>; scan: { verdict: string; findings: SkillSubmissionFinding[] }; diff: string; library_moved: boolean; notice: string }
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('admin_response_invalid'); return value as Record<string, unknown> }
function string(value: unknown): string { if (typeof value !== 'string') throw new Error('admin_response_invalid'); return value }
function nullable(value: unknown): string | null { return value == null ? null : string(value) }
function number(value: unknown): number { if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw new Error('admin_response_invalid'); return value }
function stringsRecord(value: unknown): Record<string, string> { const row = object(value); return Object.fromEntries(Object.entries(row).map(([key, item]) => [key, string(item)])) }
function submission(value: unknown): SkillSubmissionRow {
  const row = object(value)
  if (typeof row.updates_existing !== 'boolean') throw new Error('admin_response_invalid')
  return { id: string(row.id), name: string(row.name), description: string(row.description), origin: string(row.origin), state: string(row.state), verdict: string(row.verdict), findings: number(row.findings), review_reason: nullable(row.review_reason), created_at: string(row.created_at), updates_existing: row.updates_existing }
}
function base(tenantId: string): string { return `/api/v1/tenants/${encodeURIComponent(tenantId)}/admin/skill-submissions` }
/** 最多 200 条待审核项；没有游标时不虚构分页。 */
export async function listEnterpriseSkillSubmissions(tenantId: string): Promise<SkillSubmissionRow[]> {
  const data: unknown = await get(`${base(tenantId)}?state=pending`)
  if (!Array.isArray(data)) throw new Error('admin_response_invalid')
  return data.map(submission)
}
/** 读取待审核项全文、当前扫描结果和与库版本的纯文本差异。 */
export async function getEnterpriseSkillSubmission(tenantId: string, id: string): Promise<SkillSubmissionDetail> {
  const row = object(await get(`${base(tenantId)}/${encodeURIComponent(id)}/review`)), scan = object(row.scan)
  if (typeof row.library_moved !== 'boolean' || !Array.isArray(scan.findings)) throw new Error('admin_response_invalid')
  const findings = scan.findings.map(value => {
    const item = object(value)
    return { rule: string(item.rule), severity: string(item.severity), path: string(item.path), line: item.line === null ? null : number(item.line), excerpt: string(item.excerpt) }
  })
  return { ...submission(row), skill_md: string(row.skill_md), files: stringsRecord(row.files), scan: { verdict: string(scan.verdict), findings }, diff: string(row.diff), library_moved: row.library_moved, notice: string(row.notice) }
}
/** 批准后会重新扫描并发布到当前企业技能库。 */
export async function approveEnterpriseSkillSubmission(tenantId: string, id: string): Promise<void> {
  const row = object(await post(`${base(tenantId)}/${encodeURIComponent(id)}/approve`, {}, { timeout: 120_000 }))
  if (row.id !== id || row.state !== 'approved') throw new Error('admin_response_invalid')
}
/** 拒绝投稿并向提交者保存 1–1000 字的说明。 */
export async function rejectEnterpriseSkillSubmission(tenantId: string, id: string, reason: string): Promise<void> {
  const row = object(await post(`${base(tenantId)}/${encodeURIComponent(id)}/reject`, { reason }))
  if (row.id !== id || row.state !== 'rejected') throw new Error('admin_response_invalid')
}
