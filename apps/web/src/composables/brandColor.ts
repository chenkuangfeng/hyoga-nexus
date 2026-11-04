import { ref } from 'vue'
import {
  loadPreference,
  savePreference,
  migratePreferencesIntoUser,
} from './preferenceStorage'

/**
 * 全局品牌色（主题色）设置。
 *
 * 默认绿色不写入任何覆盖变量，直接沿用 `assets/theme/theme.css` 里的原始色阶，
 * 因此默认外观与未引入该功能前完全一致。选择其他颜色时，由 `applyBrandColor`
 * 以 inline style 的形式覆盖 `--td-brand-color-*` 及派生变量；inline 优先级高于
 * theme.css 的 `:root` 规则，所以浅色与深色两套都会生效。
 */

export const BRAND_COLORS = {
  green: '#07c05f',
  blue: '#1677ff',
  indigo: '#2f54eb',
  purple: '#722ed1',
  pink: '#eb2f96',
  red: '#f5222d',
  orange: '#fa8c16',
  gold: '#faad14',
  cyan: '#13c2c2',
  sky: '#0ea5e9',
  brown: '#8b5e3c',
  graphite: '#4b5563',
} as const

export type BrandColorKey = keyof typeof BRAND_COLORS

export const BRAND_COLOR_KEYS = Object.keys(BRAND_COLORS) as BrandColorKey[]

const DEFAULT_BRAND: BrandColorKey = 'green'
const STORAGE_SUFFIX = 'brand_color'

const isBrandColorKey = (v: string | null): v is BrandColorKey =>
  !!v && Object.prototype.hasOwnProperty.call(BRAND_COLORS, v)

function loadBrand(): BrandColorKey {
  const v = loadPreference(STORAGE_SUFFIX)
  return isBrandColorKey(v) ? v : DEFAULT_BRAND
}

const currentBrand = ref<BrandColorKey>(loadBrand())

const WHITE = '#ffffff'
const BLACK = '#000000'

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number]
}

function rgbToHex(rgb: number[]): string {
  return (
    '#' +
    rgb
      .map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0'))
      .join('')
  )
}

/** 按 t（0~1）在两个颜色之间做线性混合，t 为 hexB 的权重。 */
function mix(hexA: string, hexB: string, t: number): string {
  const a = hexToRgb(hexA)
  const b = hexToRgb(hexB)
  return rgbToHex(a.map((v, i) => v * (1 - t) + b[i] * t))
}

/**
 * 以 base 作为第 mainIndex 级（1 起算）生成 10 级色阶。
 *
 * 比主色浅的级别向白色混合，越靠前越浅（第 1 级约 92% 白）；
 * 比主色深的级别向黑色混合，越靠后越深（第 10 级约 85% 黑）。
 * 与 theme.css 中原始色阶的明暗走向一致，浅色主色取第 4 级，深色主色取第 6 级。
 */
export function generateBrandScale(base: string, mainIndex: number): string[] {
  const scale: string[] = []
  for (let level = 1; level <= 10; level++) {
    const d = level - mainIndex
    if (d === 0) scale.push(base)
    else if (d < 0) scale.push(mix(base, WHITE, (0.92 * -d) / (mainIndex - 1)))
    else scale.push(mix(base, BLACK, (0.85 * d) / (10 - mainIndex)))
  }
  return scale
}

type Mode = 'light' | 'dark'

/**
 * 构造某一模式下需要覆盖的全部 CSS 变量。
 * 派生规则与 theme.css 保持一致：hover / active 取主色相邻级，
 * 浅色 light 取第 1 级，深色 light 为主色的 20% 透明度底色。
 */
function buildTokens(base: string, mode: Mode): Record<string, string> {
  const main = mode === 'dark' ? 6 : 4
  const scale = generateBrandScale(base, main)
  const vars: Record<string, string> = {}
  scale.forEach((color, i) => {
    vars[`--td-brand-color-${i + 1}`] = color
  })
  const mainColor = scale[main - 1]
  vars['--td-brand-color'] = mainColor
  vars['--brand-main'] = mainColor
  vars['--td-brand-color-hover'] = scale[main - 2]
  vars['--td-brand-color-active'] = scale[main]
  vars['--td-brand-color-light'] = mode === 'dark' ? `${base}33` : scale[0]
  vars['--td-brand-color-disabled'] =
    mode === 'dark' ? mix(base, BLACK, 0.5) : mix(base, WHITE, 0.5)
  return vars
}

/** 所有可能被覆盖的变量名（与模式无关，用于恢复默认时清理）。 */
const TOKEN_NAMES = Object.keys(buildTokens(BRAND_COLORS.blue, 'light'))

function currentMode(): Mode {
  return document.documentElement.getAttribute('theme-mode') === 'dark' ? 'dark' : 'light'
}

/**
 * 把当前品牌色写入 <html>。
 * - 默认绿色：移除所有覆盖变量，回落到 theme.css 的原始值。
 * - 其他颜色：按当前模式生成并写入覆盖变量。
 * 应在主题模式切换（applyTheme）和品牌色切换时调用。
 */
export function applyBrandColor(mode: Mode = currentMode()): void {
  const root = document.documentElement
  if (!root) return
  if (currentBrand.value === DEFAULT_BRAND) {
    for (const name of TOKEN_NAMES) root.style.removeProperty(name)
    return
  }
  const tokens = buildTokens(BRAND_COLORS[currentBrand.value], mode)
  for (const [name, value] of Object.entries(tokens)) {
    root.style.setProperty(name, value)
  }
}

export function useBrandColor() {
  /** 设置全局品牌色并持久化。非法 key 返回 false，不改变当前值。 */
  function setBrandColor(key: BrandColorKey): boolean {
    if (!isBrandColorKey(key)) return false
    currentBrand.value = key
    savePreference(STORAGE_SUFFIX, key)
    applyBrandColor()
    return true
  }

  return { currentBrand, setBrandColor }
}

/** 登录或切换用户后重新读取该用户的品牌色偏好。 */
export function reloadBrandColorFromStorage() {
  migratePreferencesIntoUser()
  currentBrand.value = loadBrand()
  applyBrandColor()
}
