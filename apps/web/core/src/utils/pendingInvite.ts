/**
 * 待处理的空间邀请。未登录用户打开 `/join?code=...`（共享空间邀请码）或 `/join?token=...`（企业邀请链接）时，
 * 会先被带到登录页；邀请信息暂存在 sessionStorage 中，登录后由 `/join` 页面读取并处理。
 */
const PENDING_CODE_KEY = 'nexus_pending_invite_code'
const PENDING_TOKEN_KEY = 'nexus_pending_invite_token'

export function rememberPendingInviteCode(code: string): void {
  const trimmed = code.trim()
  if (trimmed) sessionStorage.setItem(PENDING_CODE_KEY, trimmed)
}

/** 是否有等待处理的共享空间邀请码（不清除）。 */
export function hasPendingInviteCode(): boolean {
  return !!sessionStorage.getItem(PENDING_CODE_KEY)
}

/** 读取并清除待处理的共享空间邀请码；没有则返回空字符串。 */
export function takePendingInviteCode(): string {
  const code = sessionStorage.getItem(PENDING_CODE_KEY) ?? ''
  sessionStorage.removeItem(PENDING_CODE_KEY)
  return code
}

export function rememberPendingInviteToken(token: string): void {
  const trimmed = token.trim()
  if (trimmed) sessionStorage.setItem(PENDING_TOKEN_KEY, trimmed)
}

/** 是否有等待处理的企业邀请链接（不清除）。登录后据此跳转到 `/join`。 */
export function hasPendingInviteToken(): boolean {
  return !!sessionStorage.getItem(PENDING_TOKEN_KEY)
}

/** 读取并清除待处理的企业邀请链接 token；没有则返回空字符串。 */
export function takePendingInviteToken(): string {
  const token = sessionStorage.getItem(PENDING_TOKEN_KEY) ?? ''
  sessionStorage.removeItem(PENDING_TOKEN_KEY)
  return token
}
