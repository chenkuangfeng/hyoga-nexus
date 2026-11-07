import assert from 'node:assert/strict'
import test from 'node:test'
import { failureKey, isFinishedBuild, looksLikeSource, parseInstallFailure } from './skillInstall'

test('a rule-level problem is read from the message of the generic class', () => {
  const failure = parseInstallFailure({ status: 422, message: 'bundle_invalid',
    error: { code: 'invalid_configuration', message: 'bundle_invalid' } })
  assert.equal(failure.code, 'bundle_invalid')
  assert.equal(failure.needsAck, false)
  assert.equal(failureKey(failure.code), 'nexusAgent.skillInstall.error.archive')
})

test('a scan stop carries its own code, verdict and findings, and may be released', () => {
  const failure = parseInstallFailure({ error: { code: 'skill_ack_required', message: 'skill_ack_required',
    details: { verdict: 'dangerous', findings: [{ rule: 'wipe_root_or_home', severity: 'high', category: 'destructive',
      path: 'scripts/clean.sh', line: 1, excerpt: 'rm -rf ~' }] } } })
  assert.equal(failure.needsAck, true)
  assert.equal(failure.verdict, 'dangerous')
  assert.equal(failure.findings[0].path, 'scripts/clean.sh')
  assert.equal(failureKey(failure.code), 'nexusAgent.skillInstall.error.needsAck')
})

test('a verify failure keeps its detail after the first colon', () => {
  const failure = parseInstallFailure({ error: { code: 'invalid_configuration',
    message: 'skill_verify_failed:scripts/a.py:python_syntax_error:line 1: invalid syntax' } })
  assert.equal(failure.code, 'skill_verify_failed')
  assert.equal(failure.detail, 'scripts/a.py:python_syntax_error:line 1: invalid syntax')
  assert.equal(failureKey(failure.code), 'nexusAgent.skillInstall.error.verify')
})

test('unknown or empty failures fall back without throwing', () => {
  assert.equal(failureKey(parseInstallFailure(undefined).code), 'nexusAgent.skillInstall.error.other')
  assert.equal(failureKey(parseInstallFailure(new Error('x')).code), 'nexusAgent.skillInstall.error.other')
  assert.equal(parseInstallFailure({ message: 'network down' }).message, 'network down')
})

test('every code the server can answer maps to a group', () => {
  for (const code of ['bundle_too_large', 'bundle_symlink', 'skill_source_denied', 'skill_source_http_error',
    'skill_source_confirmation_required', 'skill_install_in_progress', 'skill_version_unchanged', 'skill_name_taken_by_builtin']) {
    assert.notEqual(failureKey(code), 'nexusAgent.skillInstall.error.other', code)
  }
})

test('build states and sources', () => {
  assert.equal(isFinishedBuild('installing'), false)
  assert.equal(isFinishedBuild('ready') && isFinishedBuild('failed'), true)
  assert.equal(looksLikeSource('github:o/r/skills/x@main'), true)
  assert.equal(looksLikeSource('https://example.com/a.zip'), true)
  assert.equal(looksLikeSource('http://example.com/a.zip'), false)
  assert.equal(looksLikeSource('two words'), false)
  assert.equal(looksLikeSource(''), false)
})
