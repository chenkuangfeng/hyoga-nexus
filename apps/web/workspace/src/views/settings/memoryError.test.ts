import assert from 'node:assert/strict'
import { test } from 'node:test'
import { memoryErrorText } from './memoryError.ts'

test('memory saves display the reason carried by a rejected HTTP response object', () => {
  assert.equal(memoryErrorText({ status: 409, message: 'Memory budget would be exceeded' }, '保存失败'),
    'Memory budget would be exceeded')
  assert.equal(memoryErrorText(new Error('Duplicate memory'), '保存失败'), 'Duplicate memory')
})

test('missing, blank and malformed response messages use the translated fallback', () => {
  for (const error of [null, undefined, {}, { message: '' }, { message: ' ' }, { message: 409 }]) {
    assert.equal(memoryErrorText(error, '保存失败'), '保存失败')
  }
})
