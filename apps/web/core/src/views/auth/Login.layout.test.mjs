import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('./Login.vue', import.meta.url), 'utf8')

test('login is a single centered card without the showcase carousel', () => {
  assert.match(source, /\.login-main\s*\{[\s\S]*?align-items:\s*center;[\s\S]*?justify-content:\s*center;/)
  assert.doesNotMatch(source, /swiper/i)
  assert.doesNotMatch(source, /showcase/i)
  assert.doesNotMatch(source, /login-features/)
})

test('narrow screens keep the card inside the viewport', () => {
  assert.match(source, /@media \(max-width: 480px\)\s*\{\s*\.form-card\s*\{/)
})
