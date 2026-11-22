/** 企业知识库内容客户端：显式企业路径、运行时响应校验、沿用现有文档/FAQ/Wiki 契约。 */
import { del, get, getDown, post, postUpload, put } from '../utils/request'
import type { KnowledgeFolderNode, KnowledgeFolderTree } from './knowledge-base/index'

export type KnowledgeDocumentState = 'pending' | 'parsed' | 'embedded' | 'ready' | 'failed' | 'superseded'
export interface KnowledgeDocumentVersion {
  id: string; version: number; state: KnowledgeDocumentState; size: number; mime: string | null
  content_hash: string; chunk_count: number; indexed_count: number; error_code: string | null; error_message: string | null
  created_at: string; updated_at: string
}
export interface EnterpriseKnowledgeDocument {
  id: string; kb_id: string; filename: string; file_type: string; status: 'active'
  parse_status: string; folder_path: string; summary: string | null; tag_ids: string[]
  current_version: KnowledgeDocumentVersion | null; latest_version: KnowledgeDocumentVersion | null
  created_at: string; updated_at: string
}
export interface KnowledgeDocumentPage { items: EnterpriseKnowledgeDocument[]; total: number }
export interface EnterpriseFaqEntry {
  id: string; kb_id: string; category: string; tag_id: string | null; standard_question: string
  similar_questions: string[]; negative_questions: string[]; answers: string[]; answer_strategy: 'all' | 'first'
  is_enabled: boolean; is_recommended: boolean; index_state: string; index_error: string | null
  created_at: string; updated_at: string
}
export interface FaqEntryInput {
  standard_question: string; similar_questions: string[]; negative_questions: string[]; answers: string[]
  category: string; tag_id?: string | null; answer_strategy: 'all' | 'first'; is_enabled: boolean; is_recommended: boolean
}
export interface EnterpriseWikiPage {
  id: string; tenant_id: string; knowledge_base_id: string; slug: string; title: string; page_type: string
  status: string; content: string; summary: string; aliases: string[]; source_refs: string[]; in_links: string[]
  out_links: string[]; page_metadata: Record<string, unknown>; version: number; created_at: string; updated_at: string
}
export interface WikiPageInput { slug?: string; title: string; page_type: string; status: string; summary: string; content: string; version?: number }

const invalid = () => new Error('enterprise_knowledge_content_response_invalid')
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid(); return value as Record<string, unknown> }
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw invalid(); return value }
function string(value: unknown): string { if (typeof value !== 'string') throw invalid(); return value }
function nullableString(value: unknown): string | null { return value === null ? null : string(value) }
function count(value: unknown): number { if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw invalid(); return value }
function strings(value: unknown): string[] { return array(value).map(string) }
const root = (tenant: string) => `/api/v1/tenants/${encodeURIComponent(tenant)}/admin/knowledge`
const base = (tenant: string, kb: string) => `${root(tenant)}/bases/${encodeURIComponent(kb)}`

function versionFromResponse(value: unknown): KnowledgeDocumentVersion {
  const row = object(value), state = string(row.state)
  if (!['pending', 'parsed', 'embedded', 'ready', 'failed', 'superseded'].includes(state)) throw invalid()
  return { id: string(row.id), version: count(row.version), state: state as KnowledgeDocumentState, size: count(row.size),
    mime: nullableString(row.mime), content_hash: string(row.content_hash), chunk_count: count(row.chunk_count),
    indexed_count: count(row.indexed_count), error_code: nullableString(row.error_code), error_message: nullableString(row.error_message),
    created_at: string(row.created_at), updated_at: string(row.updated_at) }
}
function documentFromResponse(value: unknown, kb: string): EnterpriseKnowledgeDocument {
  const row = object(value), status = string(row.status)
  if (row.kb_id !== kb || status !== 'active' || !['pending', 'processing', 'finalizing', 'failed', 'cancelled', 'completed'].includes(string(row.parse_status))) throw invalid()
  return { id: string(row.id), kb_id: kb, filename: string(row.filename), file_type: string(row.file_type), status: 'active',
    parse_status: string(row.parse_status), folder_path: string(row.folder_path), summary: nullableString(row.summary), tag_ids: strings(row.tag_ids),
    current_version: row.current_version === null ? null : versionFromResponse(row.current_version),
    latest_version: row.latest_version === null ? null : versionFromResponse(row.latest_version),
    created_at: string(row.created_at), updated_at: string(row.updated_at) }
}
export async function listEnterpriseKnowledgeDocuments(tenant: string, kb: string, keyword: string, offset: number,
  limit: number, folder?: string): Promise<KnowledgeDocumentPage> {
  const query = new URLSearchParams({ keyword, offset: String(offset), limit: String(limit) })
  if (folder !== undefined) {
    query.set('folder_path', folder)
    query.set('folder_recursive', String(Boolean(keyword)))
  }
  const row = object(await get(`${base(tenant, kb)}/documents?${query}`)), items = array(row.items).map(item => documentFromResponse(item, kb))
  if (new Set(items.map(item => item.id)).size !== items.length) throw invalid()
  return { items, total: count(row.total) }
}
export async function uploadEnterpriseKnowledgeDocument(tenant: string, kb: string, file: File,
  progress?: (loaded: number, total: number) => void, fileName?: string): Promise<{ document: EnterpriseKnowledgeDocument; deduplicated: boolean }> {
  const form = new FormData(); form.append('file', file)
  if (fileName) form.append('filename', fileName)
  const result = object(await postUpload(`${base(tenant, kb)}/documents`, form, event => {
    if (event.total) progress?.(event.loaded, event.total)
  }))
  if (typeof result.deduplicated !== 'boolean') throw invalid()
  return { document: documentFromResponse(result.document, kb), deduplicated: result.deduplicated }
}

function folderFromResponse(value: unknown): KnowledgeFolderNode {
  const row = object(value)
  return { path: string(row.path), name: string(row.name), document_count: count(row.document_count),
    total_count: count(row.total_count), children: array(row.children).map(folderFromResponse) }
}
export async function listEnterpriseKnowledgeFolders(tenant: string, kb: string): Promise<KnowledgeFolderTree> {
  const row = object(await get(`${base(tenant, kb)}/folders`))
  return { root_document_count: count(row.root_document_count), total_document_count: count(row.total_document_count),
    folders: array(row.folders).map(folderFromResponse) }
}
export async function createEnterpriseKnowledgeFolder(tenant: string, kb: string, path: string): Promise<string> {
  return string(object(await post(`${base(tenant, kb)}/folders`, { path })).path)
}
export async function renameEnterpriseKnowledgeFolder(tenant: string, kb: string, source: string, target: string): Promise<void> {
  await put(`${base(tenant, kb)}/folders`, { source, target })
}
export async function retryEnterpriseKnowledgeDocument(tenant: string, id: string): Promise<void> {
  const row = object(await post(`${root(tenant)}/documents/${encodeURIComponent(id)}/retry`, {}))
  if (string(row.state) !== 'pending') throw invalid()
}
export async function deleteEnterpriseKnowledgeDocument(tenant: string, id: string): Promise<void> { await del(`${root(tenant)}/documents/${encodeURIComponent(id)}`) }
export function downloadEnterpriseKnowledgeDocument(tenant: string, id: string): Promise<Blob> { return getDown(`${root(tenant)}/documents/${encodeURIComponent(id)}/download`) }

function faqFromResponse(value: unknown, kb: string): EnterpriseFaqEntry {
  const row = object(value), strategy = string(row.answer_strategy)
  if (row.kb_id !== kb || (strategy !== 'all' && strategy !== 'first') || typeof row.is_enabled !== 'boolean' || typeof row.is_recommended !== 'boolean') throw invalid()
  return { id: string(row.id), kb_id: kb, category: string(row.category), tag_id: nullableString(row.tag_id), standard_question: string(row.standard_question),
    similar_questions: strings(row.similar_questions), negative_questions: strings(row.negative_questions), answers: strings(row.answers), answer_strategy: strategy,
    is_enabled: row.is_enabled, is_recommended: row.is_recommended, index_state: string(row.index_state), index_error: nullableString(row.index_error),
    created_at: string(row.created_at), updated_at: string(row.updated_at) }
}
export async function listEnterpriseFaqEntries(tenant: string, kb: string, keyword: string, offset: number, limit: number): Promise<{ items: EnterpriseFaqEntry[]; total: number }> {
  const query = new URLSearchParams({ keyword, offset: String(offset), limit: String(limit) }), row = object(await get(`${base(tenant, kb)}/faq/entries?${query}`))
  const items = array(row.items).map(value => faqFromResponse(value, kb))
  if (new Set(items.map(item => item.id)).size !== items.length) throw invalid()
  return { items, total: count(row.total) }
}
function faqPayload(value: FaqEntryInput): FaqEntryInput {
  if (!value.standard_question.trim() || !value.answers.some(answer => answer.trim()) || (value.answer_strategy !== 'all' && value.answer_strategy !== 'first')) throw new Error('enterprise_faq_input_invalid')
  return { ...value, standard_question: value.standard_question.trim(), answers: value.answers.map(item => item.trim()).filter(Boolean) }
}
export async function saveEnterpriseFaqEntry(tenant: string, kb: string, input: FaqEntryInput, id?: string): Promise<EnterpriseFaqEntry> {
  const url = id ? `${base(tenant, kb)}/faq/entries/${encodeURIComponent(id)}` : `${base(tenant, kb)}/faq/entries`
  const result = object(id ? await put(url, faqPayload(input)) : await post(url, faqPayload(input)))
  return faqFromResponse(result, kb)
}
export async function deleteEnterpriseFaqEntry(tenant: string, kb: string, id: string): Promise<void> {
  const result = object(await post(`${base(tenant, kb)}/faq/entries/delete`, { ids: [id] }))
  if (count(result.deleted) !== 1) throw invalid()
}

function wikiPath(tenant: string, kb: string): string { return `${base(tenant, kb)}/wiki` }
function wikiPageFromResponse(value: unknown, tenant: string, kb: string, detail: boolean): EnterpriseWikiPage {
  const row = object(value), metadata = object(row.page_metadata), content = detail ? string(row.content) : ''
  if (row.tenant_id !== tenant || row.knowledge_base_id !== kb || typeof row.version !== 'number' || !Number.isSafeInteger(row.version) || row.version < 0) throw invalid()
  return { id: string(row.id), tenant_id: tenant, knowledge_base_id: kb, slug: string(row.slug), title: string(row.title), page_type: string(row.page_type),
    status: string(row.status), content, summary: string(row.summary), aliases: strings(row.aliases), source_refs: strings(row.source_refs),
    in_links: strings(row.in_links), out_links: strings(row.out_links), page_metadata: metadata, version: row.version,
    created_at: string(row.created_at), updated_at: string(row.updated_at) }
}
function wikiSlugPath(slug: string): string { return slug.split('/').map(encodeURIComponent).join('/') }
export async function listEnterpriseWikiPages(tenant: string, kb: string, query: string, page: number, pageSize: number): Promise<{ items: EnterpriseWikiPage[]; total: number }> {
  const params = new URLSearchParams({ query, page: String(page), page_size: String(pageSize) })
  const result = object(await get(`${wikiPath(tenant, kb)}/pages?${params}`)), items = array(result.pages).map(value => wikiPageFromResponse(value, tenant, kb, false))
  if (new Set(items.map(item => item.slug)).size !== items.length) throw invalid()
  return { items, total: count(result.total) }
}
export async function getEnterpriseWikiPage(tenant: string, kb: string, slug: string): Promise<EnterpriseWikiPage> {
  return wikiPageFromResponse(await get(`${wikiPath(tenant, kb)}/pages/${wikiSlugPath(slug)}`), tenant, kb, true)
}
export async function saveEnterpriseWikiPage(tenant: string, kb: string, input: WikiPageInput, oldSlug?: string): Promise<EnterpriseWikiPage> {
  const path = wikiPath(tenant, kb)
  const result = oldSlug ? await put(`${path}/pages/${wikiSlugPath(oldSlug)}`, input) : await post(`${path}/pages`, input)
  return wikiPageFromResponse(result, tenant, kb, true)
}
export async function deleteEnterpriseWikiPage(tenant: string, kb: string, slug: string): Promise<void> {
  await del(`${wikiPath(tenant, kb)}/pages/${wikiSlugPath(slug)}`)
}
