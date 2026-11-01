import { i18n } from '../../i18n'
/** Maps login redirect error keys (from the WeCom callback) to user-facing messages. */
export function errorMessageFor(key: string): string {
  switch (key) {
    case 'unbound': return i18n.global.t('auth.unboundError')
    case 'failed': return i18n.global.t('auth.wecomFailed')
    default: return i18n.global.t('auth.loginDefault')
  }
}
