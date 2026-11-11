import { del, get, getDown } from '@/utils/request'
import { useAuthStore } from '@/stores/auth'
import { toLibraryPage, toListQuery } from './nexusArtifactAdapter'

/**
 * One file in the artifact library: the latest version of a file a Run left under `/outputs` in one of the sessions
 * the caller may see. Download it with {@link downloadArtifactFile}, which re-checks session access server side.
 * `message_id` and `index` are WeKnora leftovers and stay empty in Nexus.
 */
export interface ArtifactLibraryItem {
  /** The Nexus artifact id; downloads and deletes address the file by it. */
  id: string
  session_id: string
  session_title: string
  message_id: string
  index: number
  /** `resource://<handle>` when the deployment runs a resource catalog. */
  handle?: string
  file_name: string
  file_type: string
  file_size: number
  source_path: string
  created_at: string
  /** How many times this file was (re)generated in its session. */
  version_count: number
}

export interface ArtifactLibraryParams {
  keyword?: string
  /** Extensions such as ".pdf"; empty means every type. */
  fileTypes?: string[]
  page?: number
  pageSize?: number
}

export interface ArtifactLibraryPage {
  success: boolean
  data: ArtifactLibraryItem[]
  total: number
  page: number
  page_size: number
}

/** `/api/v1/tenants/{effective tenant}/artifacts`: files Runs left under `/outputs` (openspec 2026-11-07-tool-expansion 4.6). */
function artifactsPath(): string {
  const tenantId = useAuthStore().effectiveTenantId || ''
  return `/api/v1/tenants/${encodeURIComponent(tenantId)}/artifacts`
}

/** The newest version of each file the caller may see, with the server's total (rows carry `version_count`). */
export async function listArtifactLibrary(params: ArtifactLibraryParams = {}): Promise<ArtifactLibraryPage> {
  const res = await get(`${artifactsPath()}?${toListQuery(params)}`)
  return toLibraryPage(res as any, params.page || 1, params.pageSize || 30)
}

/** The stored copy's bytes. The server audits the download and re-checks that the caller may see the session. */
export function downloadArtifactFile(item: Pick<ArtifactLibraryItem, 'id'>): Promise<Blob> {
  return getDown(`${artifactsPath()}/${encodeURIComponent(item.id)}/download`)
}

export interface ArtifactDeleteResult {
  success: boolean
  data: { file_name: string; deleted: number }
}

/**
 * Deletes a file from the artifact library, along with every earlier version of it in the same session — a library
 * row is the file, not one regeneration of it. The stored copies are deleted, so this is not reversible. Callers
 * confirm with the user first.
 */
export async function deleteArtifactLibraryItem(item: ArtifactLibraryItem): Promise<ArtifactDeleteResult> {
  await del(`${artifactsPath()}/${encodeURIComponent(item.id)}?all_versions=true`)
  return { success: true, data: { file_name: item.file_name, deleted: item.version_count } }
}
