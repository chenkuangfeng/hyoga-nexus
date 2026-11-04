import assert from 'node:assert/strict'
import test from 'node:test'

import { BRAND_COLORS, BRAND_COLOR_KEYS, generateBrandScale } from './brandColor'

test('exposes twelve brand colors with green as the first option', () => {
  assert.equal(BRAND_COLOR_KEYS.length, 12)
  assert.equal(BRAND_COLORS.green, '#07c05f')
})

test('generated scale has ten levels and keeps the base color at the main index', () => {
  for (const mainIndex of [4, 6]) {
    const scale = generateBrandScale('#1677ff', mainIndex)
    assert.equal(scale.length, 10)
    assert.equal(scale[mainIndex - 1], '#1677ff')
    for (const color of scale) assert.match(color, /^#[0-9a-f]{6}$/)
  }
})

test('luminance decreases monotonically from level 1 (lightest) to level 10 (darkest)', () => {
  const lum = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  for (const mainIndex of [4, 6]) {
    const scale = generateBrandScale('#722ed1', mainIndex)
    for (let k = 0; k < 9; k++) {
      assert.ok(
        lum(scale[k]) > lum(scale[k + 1]),
        `level ${k + 1} should be lighter than level ${k + 2} (mainIndex ${mainIndex})`,
      )
    }
  }
})

test('extreme levels stay short of pure white, and black base keeps its darkest level', () => {
  const light = generateBrandScale('#1677ff', 4)
  assert.notEqual(light[0], '#ffffff')
  const dark = generateBrandScale('#000000', 4)
  assert.equal(dark[9], '#000000')
})
