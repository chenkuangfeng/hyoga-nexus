/** Maps login redirect error keys (from the WeCom callback) to user-facing messages. */
export function errorMessageFor(key: string): string {
  switch (key) {
    case 'unbound': return '该企业微信账号尚未绑定空间账号，请先使用账号密码登录，再在账号页绑定企业微信。'
    case 'failed': return '企业微信登录未完成，请重新扫码。'
    default: return '登录未完成，请重试。'
  }
}
