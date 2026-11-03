/**
 * 待处理的空间邀请码。未登录用户打开 `/join?code=...` 时会先被带到登录页，
 * 邀请码暂存在 sessionStorage 中，登录后由共享空间页读取并打开加入对话框。
 */
const PENDING_INVITE_KEY = 'nexus_pending_invite_code'

export function rememberPendingInviteCode(code: string): void {
  const trimmed = code.trim()
  if (trimmed) sessionStorage.setItem(PENDING_INVITE_KEY, trimmed)
}

/** 读取并清除待处理的邀请码；没有则返回空字符串。 */
export function takePendingInviteCode(): string {
  const code = sessionStorage.getItem(PENDING_INVITE_KEY) ?? ''
  sessionStorage.removeItem(PENDING_INVITE_KEY)
  return code
}
