<template>
  <!--
    The caller's private skills (openspec 2026-11-07-skill-evolution, S4). Private skills are created in conversation
    (skill_manage, then skill_save after the user confirms), belong to one user, and need no binding. This dialog lists
    them with their versions, lets the owner return to another version, delete (archive, restorable) and discard drafts.
  -->
  <t-dialog :visible="visible" :header="$t('nexusAgent.mySkills.title')" width="680px" :footer="false" :z-index="2000"
    @close="emit('update:visible', false)">
    <p class="my-hint">{{ $t('nexusAgent.mySkills.hint') }}</p>
    <t-alert v-if="error" theme="error" :message="error" class="my-alert" />
    <t-loading :loading="loading" size="small">
      <h4 class="my-heading">{{ $t('nexusAgent.mySkills.skills') }}</h4>
      <p v-if="!loading && !skills.length" class="my-empty">{{ $t('nexusAgent.mySkills.empty') }}</p>
      <div v-for="skill in skills" :key="skill.name" :class="['my-row', { 'my-row--off': !isOffered(skill) }]">
        <div class="my-line">
          <span class="my-name">{{ skill.name }}</span>
          <span v-if="skill.version" class="my-tag my-tag--muted">{{ $t('nexusAgent.skillBinding.version', { version: skill.version }) }}</span>
          <span v-for="badge in skillBadges(skill)" :key="badge" class="my-tag">{{ $t(`nexusAgent.mySkills.badge.${badge}`) }}</span>
          <span class="my-spacer" />
          <t-link theme="primary" size="small" @click="toggleVersions(skill.name)">
            {{ $t(open === skill.name ? 'nexusAgent.mySkills.hideVersions' : 'nexusAgent.mySkills.versions') }}
          </t-link>
          <t-popconfirm v-if="shareMode && isOffered(skill)"
            :content="$t(shareMode === 'share' ? 'nexusAgent.share.shareConfirm' : 'nexusAgent.share.submitConfirm')"
            @confirm="share(skill.name)">
            <t-link theme="primary" size="small">
              {{ $t(shareMode === 'share' ? 'nexusAgent.share.share' : 'nexusAgent.share.submit') }}
            </t-link>
          </t-popconfirm>
          <t-link v-if="skill.archived" theme="primary" size="small" @click="act(() => restoreMySkill(tenantId, skill.name))">
            {{ $t('nexusAgent.restore') }}
          </t-link>
          <t-popconfirm v-else :content="$t('nexusAgent.mySkills.deleteConfirm')"
            @confirm="act(() => archiveMySkill(tenantId, skill.name))">
            <t-link theme="danger" size="small">{{ $t('nexusAgent.mySkills.delete') }}</t-link>
          </t-popconfirm>
        </div>
        <p v-if="skill.description" class="my-desc">{{ skill.description }}</p>
        <p v-if="skill.version" class="my-note">{{ usageLine(skill.use_count, skill.last_used_at) }}</p>
        <p v-if="skill.latest_state === 'failed' && skill.latest_error" class="my-note my-note--warn">
          <t-icon name="error-circle" /> {{ $t('nexusAgent.mySkills.buildFailed', { reason: skill.latest_error }) }}
        </p>
        <p v-if="skill.superseded" class="my-note">{{ $t('nexusAgent.mySkills.supersededNote') }}</p>
        <ul v-if="open === skill.name" class="my-versions">
          <li v-for="item in versions" :key="item.version">
            <span>{{ $t('nexusAgent.skillBinding.version', { version: item.version }) }}</span>
            <span class="my-tag my-tag--muted">{{ item.verdict }}</span>
            <span v-if="item.build_state !== 'ready'" class="my-tag">{{ item.build_state }}</span>
            <span class="my-time">{{ item.created_at.slice(0, 16).replace('T', ' ') }}</span>
            <span v-if="item.current" class="my-tag">{{ $t('nexusAgent.mySkills.current') }}</span>
            <t-link v-else-if="item.build_state === 'ready'" theme="primary" size="small"
              @click="act(() => rollbackMySkill(tenantId, skill.name, item.version), skill.name)">
              {{ $t('nexusAgent.mySkills.useThis') }}
            </t-link>
          </li>
        </ul>
      </div>

      <h4 v-if="drafts.length" class="my-heading">{{ $t('nexusAgent.mySkills.drafts') }}</h4>
      <div v-for="draft in drafts" :key="draft.name" class="my-row">
        <div class="my-line">
          <span class="my-name">{{ draft.name }}</span>
          <span v-if="draft.editing" class="my-tag my-tag--muted">{{ $t('nexusAgent.mySkills.editing') }}</span>
          <span class="my-tag my-tag--muted">{{ $t('nexusAgent.mySkills.fileCount', { count: draft.files.length }) }}</span>
          <span class="my-spacer" />
          <t-popconfirm :content="$t('nexusAgent.mySkills.discardConfirm')"
            @confirm="act(() => deleteMySkillDraft(tenantId, draft.name))">
            <t-link theme="danger" size="small">{{ $t('nexusAgent.mySkills.discard') }}</t-link>
          </t-popconfirm>
        </div>
        <p class="my-note">{{ $t('nexusAgent.mySkills.draftNote') }}</p>
      </div>
      <h4 v-if="submissions.length" class="my-heading">{{ $t('nexusAgent.share.mine') }}</h4>
      <div v-for="item in submissions" :key="item.id" class="my-row">
        <div class="my-line">
          <span class="my-name">{{ item.name }}</span>
          <span class="my-tag my-tag--muted">{{ $t(`nexusAgent.share.state.${item.state}`) }}</span>
          <span class="my-time">{{ item.created_at.slice(0, 16).replace('T', ' ') }}</span>
          <span class="my-spacer" />
          <t-link v-if="item.state === 'pending'" theme="danger" size="small"
            @click="act(() => withdrawSubmission(tenantId, item.id))">{{ $t('nexusAgent.share.withdraw') }}</t-link>
        </div>
        <p v-if="item.state === 'rejected' && item.review_reason" class="my-note my-note--warn">
          <t-icon name="error-circle" /> {{ $t('nexusAgent.share.rejectedBecause', { reason: item.review_reason }) }}
        </p>
      </div>
    </t-loading>
  </t-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  archiveMySkill, deleteMySkillDraft, getMyApiPermissions, listMySkills, listMySkillVersions, listMySubmissions,
  restoreMySkill, rollbackMySkill, shareMySkill, submitMySkill, withdrawSubmission,
  type MySkill, type MySkillDraft, type MySkillVersion, type SkillSubmission,
} from '@/api/nexus-agents'
import { isOffered, shareAction, skillBadges, submissionErrorKey, usageText } from './mySkills'
import { parseInstallFailure } from './skillInstall'

const props = defineProps<{ visible: boolean, tenantId: string }>()
const emit = defineEmits<{ (event: 'update:visible', value: boolean): void, (event: 'changed'): void }>()
const { t } = useI18n()

const loading = ref(false)
const error = ref('')
const skills = ref<MySkill[]>([])
const drafts = ref<MySkillDraft[]>([])
const versions = ref<MySkillVersion[]>([])
const open = ref('')
const submissions = ref<SkillSubmission[]>([])
const shareMode = ref<'share' | 'submit' | null>(null)

function usageLine(count: number, last: string | null): string {
  const usage = usageText(count, last)
  if (!usage) return ''
  return usage.kind === 'never' ? t('nexusAgent.usage.never') : t('nexusAgent.usage.line', { count: usage.count, when: usage.when })
}

function message(failure: unknown): string {
  const parsed = parseInstallFailure(failure)
  if (parsed.code) {
    const key = submissionErrorKey(parsed.code)
    if (!key.endsWith('.other')) return t(key)
  }
  return parsed.message || t('nexusAgent.mySkills.failed')
}

/** Administrators publish a private skill straight into the library; members with `skills:submit` file a submission. */
async function share(name: string) {
  const mode = shareMode.value
  if (!mode) return
  await act(async () => {
    if (mode === 'share') await shareMySkill(props.tenantId, name)
    else await submitMySkill(props.tenantId, name)
    MessagePlugin.success(t(mode === 'share' ? 'nexusAgent.share.shared' : 'nexusAgent.share.submitted'))
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const listed = await listMySkills(props.tenantId)
    skills.value = listed.skills
    drafts.value = listed.drafts
    submissions.value = await listMySubmissions(props.tenantId).catch(() => [])
    shareMode.value = shareAction(await getMyApiPermissions(props.tenantId).catch(() => []))
  } catch (failure) {
    error.value = message(failure)
  } finally {
    loading.value = false
  }
}

async function toggleVersions(name: string) {
  if (open.value === name) { open.value = ''; return }
  open.value = name
  versions.value = []
  try {
    versions.value = await listMySkillVersions(props.tenantId, name)
  } catch (failure) {
    error.value = message(failure)
  }
}

/** Run one change, then refresh the list (and the open version list), telling the editor something changed. */
async function act(change: () => Promise<void>, refreshVersionsOf = '') {
  error.value = ''
  try {
    await change()
    emit('changed')
  } catch (failure) {
    error.value = message(failure)
  }
  await load()
  if (refreshVersionsOf && open.value === refreshVersionsOf) {
    try { versions.value = await listMySkillVersions(props.tenantId, refreshVersionsOf) } catch { /* shown by load */ }
  }
}

watch(() => props.visible, (shown) => { if (shown) { open.value = ''; void load() } }, { immediate: true })
</script>

<style scoped>
.my-hint { margin: 0 0 8px; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.my-alert { margin-bottom: 8px; }
.my-heading { margin: 12px 0 6px; font-size: var(--app-text-sm); }
.my-empty { margin: 0; font-size: var(--app-text-sm); color: var(--td-text-color-secondary); }
.my-row { padding: 8px 0; border-bottom: 1px solid var(--td-component-stroke); }
.my-row--off .my-name { color: var(--td-text-color-secondary); }
.my-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.my-name { font-weight: 600; word-break: break-all; }
.my-spacer { flex: 1; }
.my-tag { padding: 0 6px; font-size: var(--app-text-xs); border: 1px solid var(--td-warning-color); color: var(--td-warning-color); border-radius: var(--td-radius-small); }
.my-tag--muted { border-color: var(--td-component-border); color: var(--td-text-color-secondary); }
.my-desc, .my-note { margin: 4px 0 0; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.my-note--warn { color: var(--td-warning-color); }
.my-versions { margin: 6px 0 0; padding: 0; list-style: none; font-size: var(--app-text-xs); }
.my-versions li { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.my-time { color: var(--td-text-color-secondary); }
</style>
