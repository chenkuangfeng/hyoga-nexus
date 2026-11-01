/**
 * Interface languages (zh-CN, en-US). The choice is stored in localStorage; without one, the browser
 * language decides. Components read text with `t(key)` from `useI18n()`; never hard-code user-visible text.
 *
 * Keys are nested by area (`shell.*`, `chat.*`, `settings.*` ...). A missing English key falls back to Chinese.
 */
import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'

export type Locale = 'zh-CN' | 'en-US'
export const LOCALES: { value: Locale; label: string }[] = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'en-US', label: 'English' },
]
const STORAGE_KEY = 'nexus_locale'

/** The stored choice if it is a supported language, otherwise a guess from the browser. */
export function initialLocale(): Locale {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
  if (stored === 'zh-CN' || stored === 'en-US') return stored
  return typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('en') ? 'en-US' : 'zh-CN'
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'zh-CN',
  messages: { 'zh-CN': zhCN, 'en-US': enUS },
})

/** Switch the interface language and remember it. */
export function setLocale(locale: Locale): void {
  i18n.global.locale.value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  document.documentElement.lang = locale
}

document.documentElement.lang = i18n.global.locale.value
