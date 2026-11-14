/**
 * Settings sections implemented in the current phase (see openspec/changes/2026-11-03-enterprise-personal-spaces;
 * `models` since 2026-11-05-weknora-agent-tool-model-settings; `memory` and `mymemory` since 2026-11-05-memory-switches;
 * `vectorstore` and `storage` since 2026-11-06-knowledge-base K1).
 *
 * The settings navigation keeps every Nexus entry so the menu is complete. A section outside this
 * set renders the planned-page notice instead of its copied content, which still targets Nexus's
 * backend contracts. A later phase adds its key here when the section is implemented against the Nexus API.
 */
export const PHASE1_SETTINGS_SECTIONS: ReadonlySet<string> = new Set([
  'general',
  'mcp-endpoints',
  'models',
  'memory',
  'mymemory',
  'userprofile',
  'members',
  // 旧书签已实现迁移说明，不再加载部门管理实现。
  'org-structure',
  'vectorstore',
  'storage',
])

export function isPhase1Section(key: string): boolean {
  return PHASE1_SETTINGS_SECTIONS.has(key)
}
