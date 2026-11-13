import { MessagePlugin } from 'tdesign-vue-next'
import i18n from '@nexus-web/core/i18n/index'

/**
 * Copy text to the clipboard, falling back to a hidden textarea +
 * document.execCommand('copy') when the async Clipboard API is unavailable
 * (e.g. on non-secure HTTP origins) or rejects (e.g. permission denied).
 *
 * Returns true on success, false otherwise. This helper is UI-agnostic —
 * callers own any feedback. Use copyWithToast for the common "copy + toast"
 * case; call this directly when you need custom feedback (e.g. inline DOM
 * state) or none at all.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (!text) return false
  if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try { await navigator.clipboard.writeText(text); return true }
    catch { /* Permission rejection also falls back to the HTTP-compatible path. */ }
  }
  if (typeof document === 'undefined') return false
  const previous = document.activeElement as HTMLElement | null
  let textArea: HTMLTextAreaElement | undefined
  try {
    textArea = document.createElement('textarea')
    textArea.value = text
    textArea.style.position = 'fixed'
    textArea.style.top = '0'
    textArea.style.left = '0'
    textArea.style.opacity = '0'
    document.body.appendChild(textArea)
    textArea.focus()
    textArea.select()
    return document.execCommand('copy')
  } catch { return false }
  finally {
    // Failure must not leave copied invitation tokens in a hidden DOM node.
    if (textArea) { textArea.value = ''; textArea.remove() }
    try { previous?.focus({ preventScroll: true }) } catch { /* Focus restoration is best effort. */ }
  }
}

/**
 * Copy text and surface the result via a toast. Returns the underlying
 * copyToClipboard result so callers can run extra side effects on success
 * (e.g. closing a dialog). Empty / null / undefined text is a silent no-op
 * (no toast), so callers can pass optional values (e.g. obj.value?.id)
 * without a separate guard. successKey is required; failureKey defaults to
 * the common message.
 */
export async function copyWithToast(
  text: string | null | undefined,
  successKey: string,
  failureKey: string = 'common.copyFailed',
): Promise<boolean> {
  if (!text) return false
  const ok = await copyToClipboard(text)
  if (ok) {
    MessagePlugin.success(i18n.global.t(successKey))
  } else {
    MessagePlugin.error(i18n.global.t(failureKey))
  }
  return ok
}
