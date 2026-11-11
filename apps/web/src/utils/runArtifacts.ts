/**
 * Artifacts of a conversation grouped by the Run that left them, for the cards under each answer
 * (openspec 2026-11-07-tool-expansion 4.6). Pure functions, no request helpers.
 */
import type { ArtifactLibraryItem } from '@/api/artifacts'

/** Artifacts keyed by `run_id`, each group ordered by file path so a card lists files predictably. */
export function groupArtifactsByRun(items: readonly ArtifactLibraryItem[]): Map<string, ArtifactLibraryItem[]> {
  const groups = new Map<string, ArtifactLibraryItem[]>()
  for (const item of items) {
    if (!item.run_id) continue
    const group = groups.get(item.run_id)
    if (group) group.push(item)
    else groups.set(item.run_id, [item])
  }
  for (const group of groups.values()) group.sort((a, b) => a.source_path.localeCompare(b.source_path))
  return groups
}

/** How many files a card shows before it offers to expand. */
export const COLLAPSED_LIMIT = 4

/** The files to show now and how many stay hidden behind the expander. */
export function visibleArtifacts<T>(items: readonly T[], expanded: boolean, limit = COLLAPSED_LIMIT): { shown: T[], hidden: number } {
  if (expanded || items.length <= limit) return { shown: [...items], hidden: 0 }
  return { shown: items.slice(0, limit), hidden: items.length - limit }
}
