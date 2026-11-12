<template>
  <!--
    Toolbox "Skills" tab (openspec 2026-11-08-toolbox): the space's skill library, the caller's private skills, the review
    queue and installation. The last three are the panels that also run in dialogs inside the agent editor.
  -->
  <div class="tbs">
    <t-radio-group v-model="view" variant="default-filled" class="tbs-nav" :aria-label="$t('settings.skills.title')">
      <t-radio-button value="library">{{ $t('toolbox.skills.library') }}</t-radio-button>
      <t-radio-button value="mine">{{ $t('toolbox.skills.mine') }}</t-radio-button>
      <t-radio-button v-if="isAdmin" value="review">{{ $t('toolbox.skills.review') }}</t-radio-button>
      <t-radio-button v-if="isAdmin" value="install">{{ $t('toolbox.skills.install') }}</t-radio-button>
    </t-radio-group>

    <template v-if="view === 'library'">
      <t-alert v-if="error" theme="error" :message="error" class="tbs-alert" />
      <t-loading :loading="loading" size="small">
        <p v-if="!loading && !rows.length" class="tbs-empty">{{ $t('toolbox.skills.empty') }}</p>
        <table v-if="rows.length" class="tbs-table">
          <thead>
            <tr>
              <th scope="col">{{ $t('toolbox.skills.colName') }}</th>
              <th scope="col">{{ $t('toolbox.skills.colVersion') }}</th>
              <th scope="col">{{ $t('toolbox.skills.colUsage') }}</th>
              <th scope="col">{{ $t('toolbox.skills.colScripts') }}</th>
              <th scope="col" class="tbs-actions-col"><span class="visually-hidden">{{ $t('toolbox.skills.colActions') }}</span></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="skill in rows" :key="`${skill.scope}:${skill.name}`">
              <tr :class="{ 'tbs-off': skill.disabled }">
                <td>
                  <div class="tbs-name">{{ skill.name }}</div>
                  <div v-if="skill.description" class="tbs-desc">{{ skill.description }}</div>
                  <div class="tbs-badges">
                    <span v-for="badge in rowBadges(skill)" :key="badge" class="tbs-badge">{{ $t(`toolbox.skills.badge.${badge}`) }}</span>
                  </div>
                </td>
                <td>{{ skill.version ? $t('nexusAgent.skillBinding.version', { version: skill.version }) : '—' }}</td>
                <td class="tbs-usage">{{ usageLine(skill) }}</td>
                <td>
                  <span v-if="runState(skill).kind === 'none'">—</span>
                  <span v-else-if="runState(skill).kind === 'ok'" class="tbs-ok"><t-icon name="check-circle" /> {{ $t('toolbox.skills.runOk') }}</span>
                  <span v-else class="tbs-warn"><t-icon name="error-circle" /> {{ runReason(skill) }}</span>
                </td>
                <td class="tbs-actions">
                  <t-link theme="primary" size="small" @click="toggle(skill.name)">
                    {{ $t(open === skill.name ? 'nexusAgent.mySkills.hideVersions' : 'nexusAgent.mySkills.versions') }}
                  </t-link>
                  <t-link v-if="skill.version" theme="primary" size="small" @click="download(skill.name)">{{ $t('toolbox.skills.export') }}</t-link>
                  <template v-if="isAdmin && skill.scope === 'builtin'">
                    <t-link v-if="skill.disabled" theme="primary" size="small" @click="act(() => restoreBuiltinResource(tenantId, 'skill', skill.name))">
                      {{ $t('nexusAgent.restore') }}
                    </t-link>
                    <t-popconfirm v-else :content="$t('nexusAgent.disableHint')" @confirm="act(() => disableBuiltinResource(tenantId, 'skill', skill.name))">
                      <t-link theme="default" size="small">{{ $t('nexusAgent.disableHere') }}</t-link>
                    </t-popconfirm>
                  </template>
                </td>
              </tr>
              <tr v-if="open === skill.name" class="tbs-versions-row">
                <td colspan="5">
                  <ul class="tbs-versions">
                    <li v-for="item in versions" :key="item.version">
                      <span>{{ $t('nexusAgent.skillBinding.version', { version: item.version }) }}</span>
                      <span class="tbs-badge tbs-badge--muted">{{ item.trust }}</span>
                      <span class="tbs-badge tbs-badge--muted">{{ item.verdict }}</span>
                      <span v-if="item.build_state !== 'ready'" class="tbs-badge">{{ item.build_state }}</span>
                      <span v-if="item.rescan_needed" class="tbs-badge">{{ $t('toolbox.skills.badge.rescan') }}</span>
                      <span v-if="item.origin?.label" class="tbs-origin">{{ item.origin.label }}</span>
                      <span class="tbs-time">{{ item.created_at.slice(0, 16).replace('T', ' ') }}</span>
                      <t-link v-if="item.has_bundle" theme="primary" size="small" @click="download(skill.name, item.version)">
                        {{ $t('toolbox.skills.export') }}
                      </t-link>
                      <t-link v-if="isAdmin && skill.scope === 'space'" theme="primary" size="small"
                        @click="act(() => rescanSkillVersion(tenantId, skill.name, item.version), skill.name)">
                        {{ $t('toolbox.skills.rescan') }}
                      </t-link>
                    </li>
                  </ul>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </t-loading>
    </template>

    <NexusMySkillsPanel v-else-if="view === 'mine'" :tenant-id="tenantId" @changed="load" />
    <NexusSkillReviewPanel v-else-if="view === 'review' && isAdmin" :tenant-id="tenantId" @changed="load" />
    <NexusSkillInstallPanel v-else-if="view === 'install' && isAdmin" :tenant-id="tenantId" @installed="load" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  disableBuiltinResource, downloadSkillBundle, getMyApiPermissions, listSkillVersions, listTenantSkills,
  rescanSkillVersion, restoreBuiltinResource, type SkillVersionInfo, type TenantSkill,
} from '@nexus-web/core/api/nexus-agents'
import NexusMySkillsPanel from '@/views/agent/NexusMySkillsPanel.vue'
import NexusSkillReviewPanel from '@/views/agent/NexusSkillReviewPanel.vue'
import NexusSkillInstallPanel from '@/views/agent/NexusSkillInstallPanel.vue'
import { usageText } from '@/views/agent/mySkills'
import { bundleFileName, rowBadges, runReasonKey, runState, sortLibrary } from './toolboxSkills'

const props = defineProps<{ tenantId: string }>()
const emit = defineEmits<{ (event: 'count', value: number): void }>()
const { t } = useI18n()

const view = ref<'library' | 'mine' | 'review' | 'install'>('library')
const loading = ref(false)
const error = ref('')
const skills = ref<TenantSkill[]>([])
const isAdmin = ref(false)
const open = ref('')
const versions = ref<SkillVersionInfo[]>([])
const rows = computed(() => sortLibrary(skills.value))

function failure(cause: unknown): string {
  const record = (cause && typeof cause === 'object' ? cause : {}) as Record<string, unknown>
  return typeof record.message === 'string' && record.message ? record.message : t('nexusAgent.mySkills.failed')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    // An empty profile name asks about the deployment's default sandbox profile.
    skills.value = await listTenantSkills(props.tenantId, '')
    emit('count', skills.value.length)
  } catch (cause) {
    error.value = failure(cause)
  } finally {
    loading.value = false
  }
}

async function toggle(name: string) {
  if (open.value === name) { open.value = ''; return }
  open.value = name
  versions.value = []
  try {
    versions.value = await listSkillVersions(props.tenantId, name)
  } catch (cause) {
    error.value = failure(cause)
  }
}

async function act(change: () => Promise<void>, reopen = '') {
  error.value = ''
  try {
    await change()
  } catch (cause) {
    error.value = failure(cause)
  }
  await load()
  if (reopen) { open.value = ''; await toggle(reopen) }
}

async function download(name: string, version?: number) {
  try {
    const blob = await downloadSkillBundle(props.tenantId, name, version)
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = bundleFileName(name, version)
    link.click()
    URL.revokeObjectURL(link.href)
  } catch (cause) {
    MessagePlugin.error(failure(cause))
  }
}

function usageLine(skill: TenantSkill): string {
  const usage = usageText(skill.use_count, skill.last_used_at)
  if (!usage) return '—'
  return usage.kind === 'never' ? t('nexusAgent.usage.never') : t('nexusAgent.usage.line', { count: usage.count, when: usage.when })
}

function runReason(skill: TenantSkill): string {
  const state = runState(skill)
  if (state.kind !== 'blocked') return ''
  return t('toolbox.skills.runBlocked', { reason: t(runReasonKey(state.reason)) })
}

onMounted(async () => {
  isAdmin.value = (await getMyApiPermissions(props.tenantId).catch(() => [])).includes('tools:manage')
})
watch(() => props.tenantId, () => { open.value = ''; void load() }, { immediate: true })
</script>

<style scoped>
.tbs-nav { margin-bottom: 12px; }
.tbs-alert { margin-bottom: 8px; }
.tbs-empty { margin: 0; color: var(--td-text-color-secondary); font-size: var(--app-text-sm); }
.tbs-table { width: 100%; border-collapse: collapse; font-size: var(--app-text-sm); }
.tbs-table th { text-align: left; padding: 8px; font-weight: 600; color: var(--td-text-color-secondary); border-bottom: 1px solid var(--td-component-stroke); }
.tbs-table td { padding: 10px 8px; vertical-align: top; border-bottom: 1px solid var(--td-component-stroke); }
.tbs-off .tbs-name { color: var(--td-text-color-secondary); }
.tbs-name { font-weight: 600; word-break: break-all; }
.tbs-desc { margin-top: 2px; font-size: var(--app-text-xs); color: var(--td-text-color-secondary); line-height: 1.5; }
.tbs-badges { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
.tbs-badge { padding: 0 6px; font-size: var(--app-text-xs); border: 1px solid var(--td-warning-color); color: var(--td-warning-color); border-radius: var(--td-radius-small); }
.tbs-badge--muted { border-color: var(--td-component-border); color: var(--td-text-color-secondary); }
.tbs-usage { font-size: var(--app-text-xs); color: var(--td-text-color-secondary); }
.tbs-ok { color: var(--td-success-color); }
.tbs-warn { color: var(--td-warning-color); }
.tbs-actions { white-space: nowrap; }
.tbs-actions :deep(.t-link) { margin-right: 10px; }
.tbs-versions { margin: 0; padding: 0; list-style: none; font-size: var(--app-text-xs); }
.tbs-versions li { display: flex; align-items: center; gap: 8px; padding: 3px 0; flex-wrap: wrap; }
.tbs-time, .tbs-origin { color: var(--td-text-color-secondary); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
</style>
