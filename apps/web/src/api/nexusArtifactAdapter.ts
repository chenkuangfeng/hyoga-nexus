/**
 * Adapter between Nexus sandbox artifacts and the library shape the copied artifact page reads
 * (openspec 2026-11-07-tool-expansion 4.6).
 *
 * A Nexus artifact is one file a Run left under `/outputs`, addressed by its own id. The WeKnora library addressed a
 * file by message and index and showed one row per file with a version count; Nexus returns that with
 * `latest=true`. Pure functions with no request helpers, so they are unit tested directly.
 */
import type { ArtifactLibraryItem } from './artifacts'

type Json = Record<string, any>

/** The lower-case extension of a file name without the dot, or '' (the page's `file_type` is an extension, not a MIME type). */
export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 || dot === name.length - 1 ? '' : name.slice(dot + 1).toLowerCase()
}

/** One artifact of `GET /artifacts` as a library row. `message_id` and `index` do not exist in Nexus. */
export function toLibraryItem(item: Json): ArtifactLibraryItem {
  const name = String(item.name || '')
  return {
    id: String(item.id),
    session_id: String(item.session_id || ''),
    run_id: String(item.run_id || ''),
    session_title: String(item.session_title || ''),
    message_id: '',
    index: 0,
    file_name: name,
    file_type: extensionOf(name),
    file_size: Number(item.size || 0),
    source_path: String(item.path || ''),
    created_at: String(item.created_at || ''),
    version_count: Math.max(1, Number(item.version_count || 1)),
  }
}

/** Query string of `GET /artifacts` for the library's filters and page (1-based). */
export function toListQuery(params: { keyword?: string, fileTypes?: string[], page?: number, pageSize?: number }): string {
  const pageSize = Math.max(1, Math.min(200, params.pageSize || 30))
  const page = Math.max(1, params.page || 1)
  const query = new URLSearchParams({ latest: 'true', limit: String(pageSize), offset: String((page - 1) * pageSize) })
  const keyword = params.keyword?.trim()
  if (keyword) query.set('q', keyword)
  if (params.fileTypes?.length) query.set('extensions', params.fileTypes.join(','))
  return query.toString()
}

/** The library page: rows plus the total the server counted (falls back to the rows when it sent none). */
export function toLibraryPage(res: Json, page: number, pageSize: number) {
  const rows: Json[] = Array.isArray(res?.items) ? res.items : []
  return {
    success: true,
    data: rows.map(toLibraryItem),
    total: typeof res?.total === 'number' ? res.total : rows.length,
    page,
    page_size: pageSize,
  }
}
