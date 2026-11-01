import { ApiError, request } from './chat'

export interface CurrentUser { user_id: string; display_name: string | null; providers: string[]; is_platform_admin: boolean }

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('登录数据格式无效')
  return value as Record<string, unknown>
}
function text(value: unknown): string { if (typeof value !== 'string') throw new Error('登录数据格式无效'); return value }
const json = (method: string, value?: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, ...(value === undefined ? {} : { body: JSON.stringify(value) }) })

/** Sign-in requests. Passwords are sent once and never stored by the client. */
export const authApi = {
  /** Returns null when no session exists (401), so the app can show the sign-in page. */
  async me(signal?: AbortSignal): Promise<CurrentUser | null> {
    try {
      return await request<CurrentUser>('/auth/me', value => {
        const row = record(value)
        if (!Array.isArray(row.providers)) throw new Error('登录数据格式无效')
        return { user_id: text(row.user_id), display_name: row.display_name === null ? null : text(row.display_name), providers: row.providers.map(text), is_platform_admin: row.is_platform_admin === true }
      }, { signal })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null
      throw error
    }
  },
  login: (username: string, password: string) => request('/auth/login', () => undefined, json('POST', { username, password })),
  logout: () => request('/auth/logout', () => undefined, json('POST')),
  changePassword: (current_password: string, new_password: string) => request('/auth/password', () => undefined, json('POST', { current_password, new_password })),
  wecomBindStart: () => request<string>('/auth/wecom/bind/start', value => text(record(value).authorize_url), json('POST')),
  /** Browser entry point for QR sign-in; the server redirects to WeCom. */
  wecomLoginUrl: '/api/v1/auth/wecom/start',
}
