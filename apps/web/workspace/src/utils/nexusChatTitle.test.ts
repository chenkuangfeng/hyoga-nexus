import assert from 'node:assert/strict'
import { test } from 'node:test'

import { deriveSessionTitle } from './nexusChatTitle.ts'

test('title is the first message with whitespace collapsed', () => {
  assert.equal(deriveSessionTitle('  帮我  总结\n\n这份文档 '), '帮我 总结 这份文档')
})

test('title is capped at 40 characters', () => {
  assert.equal(deriveSessionTitle('a'.repeat(60)).length, 40)
})

test('blank message yields an empty title', () => {
  assert.equal(deriveSessionTitle('   \n '), '')
})
