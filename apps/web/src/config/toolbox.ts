import type { SettingsRoleKey } from './settingsAccess'
import type { DeploymentCapabilityKey } from './deploymentCapabilities'
import { SKILL_ICON } from '../types/mention'

/**
 * Toolbox tabs (openspec 2026-11-08-toolbox). `available` marks the tabs Nexus has a backend for; the others stay in the
 * bar, disabled and labelled "planned", and never issue a request.
 */
export const TOOLBOX_ITEMS = [
  {
    key: 'skills',
    icon: SKILL_ICON,
    title: 'settings.skills.title',
    description: 'toolbox.skills.description',
    available: true,
  },
  {
    key: 'tools',
    icon: 'tools',
    title: 'toolbox.tools.title',
    description: 'toolbox.tools.description',
    available: true,
  },
  {
    key: 'mcp',
    icon: 'link',
    title: 'settings.mcpService',
    description: 'mcpSettings.description',
    available: true,
  },
  {
    key: 'browserconnection',
    icon: 'browse',
    title: 'localBrowser.settingsTitle',
    description: 'localBrowser.settingsDescription',
    available: false,
  },
] as const

export type ToolboxSection = typeof TOOLBOX_ITEMS[number]['key']

export function isToolboxSection(section: unknown): section is ToolboxSection {
  return TOOLBOX_ITEMS.some((item) => item.key === section)
}

export function toolboxLocation(section?: ToolboxSection, sandboxId?: string) {
  return {
    path: section ? `/platform/toolbox/${section}` : '/platform/toolbox',
    query: section === 'skills' && sandboxId ? { sandboxId } : {},
  }
}

/** Whether the tab can be opened at all: the backend exists for it. */
export function isToolboxSectionAvailable(section: ToolboxSection): boolean {
  return TOOLBOX_ITEMS.some((item) => item.key === section && item.available)
}

/**
 * Every active member sees the toolbox; what a member may change is decided by the server on each call (`tools:manage`,
 * `skills:submit`), and the panels only hide the buttons a member cannot use.
 */
export function canAccessToolboxSection(
  section: ToolboxSection,
  access: {
    currentTenantRole: string | null | undefined
    canAccessAllTenants: boolean
    hasRole?: (role: SettingsRoleKey) => boolean
    isSupported?: (capability?: DeploymentCapabilityKey) => boolean
  },
): boolean {
  void section
  return !!access.currentTenantRole || access.canAccessAllTenants
}
