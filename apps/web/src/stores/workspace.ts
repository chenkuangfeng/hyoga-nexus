/**
 * Shared shell state: the signed-in user, the current space (工作空间) and that space's session list.
 *
 * The space selector in the sidebar writes `tenantId`; pages read it and reload when it changes.
 * The sidebar's session list is loaded here so it stays visible on every page.
 */
import { reactive } from 'vue'
import { api } from '../api/chat'
import type { CurrentUser } from '../api/auth'
import type { Conversation, Tenant } from '../types/chat'
import { i18n } from '../i18n'

const STORAGE_KEY = 'nexus_space'

export const workspace = reactive({
  user: null as CurrentUser | null,
  tenants: [] as Tenant[],
  tenantId: (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) || '',
  sessions: [] as Conversation[],
  sessionsError: '',
  /** Bumped by the sidebar's 新对话 button; the conversation page starts a blank draft when it changes. */
  newChatTick: 0,
})

let sessionsRequest = 0

/** Load the spaces the user can use and keep the stored choice only if it is still available. */
export async function loadTenants(): Promise<void> {
  workspace.tenants = await api.tenants()
  if (!workspace.tenants.some(item => item.id === workspace.tenantId)) setTenant(workspace.tenants[0]?.id || '')
  else await loadSessions()
}

/** Change the current space and refresh the sidebar's session list. */
export function setTenant(id: string): void {
  workspace.tenantId = id
  if (id) localStorage.setItem(STORAGE_KEY, id)
  else localStorage.removeItem(STORAGE_KEY)
  void loadSessions()
}

export async function loadSessions(): Promise<void> {
  const request = ++sessionsRequest
  const tenant = workspace.tenantId
  workspace.sessionsError = ''
  if (!tenant) { workspace.sessions = []; return }
  try {
    const rows = await api.sessions(tenant)
    if (request === sessionsRequest) workspace.sessions = rows
  } catch (cause) {
    if (request === sessionsRequest) { workspace.sessions = []; workspace.sessionsError = cause instanceof Error ? cause.message : i18n.global.t('shell.sessionsError') }
  }
}
