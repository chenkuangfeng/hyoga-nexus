import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../../../../core/src/components/knowledge-editor/KnowledgeBaseEditorModal.vue', import.meta.url), 'utf8')

test('editing a knowledge base closes the editor after a successful save', () => {
  assert.match(source, /emit\('success', kbId\)[\s\S]{0,100}handleClose\(\)/)
})

test('the first successful create stays open for follow-up configuration', () => {
  const createBranch = source.match(
    /if \(editorMode\.value === 'create'\) \{([\s\S]*?)^\s{4}\} else \{/m
  )?.[1]

  assert.ok(createBranch, 'expected to find the create branch')
  assert.doesNotMatch(createBranch, /handleClose\(\)/)
  assert.match(createBranch, /savedKbId\.value = createdKbId/)
})

test('save button labels distinguish create from save-and-close', () => {
  assert.match(
    source,
    /const saveButtonLabel = computed\(\(\) =>\s*editorMode\.value === 'create'\s*\? t\('knowledgeEditor\.buttons\.create'\)\s*: t\('knowledgeEditor\.buttons\.saveAndClose'\)\s*\)/
  )
})

test('shows a post-create hint after the first successful save', () => {
  assert.match(source, /const isPostCreateSession = computed\(\(\) => !!savedKbId\.value\)/)
  assert.match(source, /settings-footer-note/)
  assert.match(source, /knowledgeEditor\.postCreateHint\.followUpDesc/)
})

test('create mode seeds the full default image actions table', () => {
  // Regression: an empty imageActions in initFormData made the attribute panel
  // read `undefined.ocr.on` the moment the attribute switch was turned on in the
  // create dialog, crashing the modal.
  const initBlock = source.match(/const initFormData[\s\S]*?imageActions: ([^,]+),/)?.[1]
  assert.ok(initBlock, 'expected to find imageActions in initFormData')
  assert.match(initBlock, /mergeImageActions\(\)/)
})

test('edit mode submits the complete built configuration through one scoped update', () => {
  assert.match(source, /await updateEditableKnowledge\(tenant, kbId, \{ \.\.\.data, visibility: visibility.value \}, settingsSnapshot.value/)
  assert.doesNotMatch(source, /await updateKBConfig\(/)
})
