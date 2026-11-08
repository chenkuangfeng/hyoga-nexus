<template>
  <!--
    Review of skill submissions (openspec 2026-11-07-skill-evolution, S5). Administrators only; the server checks again.
    Everything a submitter wrote is shown as plain text: never rendered as markup, because the author is not trusted.
  -->
  <t-dialog :visible="visible" :header="$t('nexusAgent.review.title')" width="760px" :footer="false" :z-index="2000"
    @close="emit('update:visible', false)">
    <t-alert v-if="error" theme="error" :message="error" class="rv-alert" />
    <t-loading :loading="loading" size="small">
      <template v-if="!detail">
        <p v-if="!loading && !queue.length" class="rv-empty">{{ $t('nexusAgent.review.empty') }}</p>
        <div v-for="item in queue" :key="item.id" class="rv-row">
          <span class="rv-name">{{ item.name }}</span>
          <span class="rv-tag">{{ item.verdict }}</span>
          <span v-if="item.updates_existing" class="rv-tag rv-tag--muted">{{ $t('nexusAgent.review.updatesExisting') }}</span>
          <span class="rv-time">{{ item.created_at.slice(0, 16).replace('T', ' ') }}</span>
          <span class="rv-spacer" />
          <t-link theme="primary" size="small" @click="openReview(item.id)">{{ $t('nexusAgent.review.open') }}</t-link>
        </div>
      </template>
      <template v-else>
        <t-link theme="primary" size="small" @click="detail = null">{{ $t('nexusAgent.review.back') }}</t-link>
        <h4 class="rv-heading">{{ detail.name }} <span class="rv-tag">{{ detail.scan.verdict }}</span></h4>
        <p class="rv-notice"><t-icon name="error-circle" /> {{ $t('nexusAgent.review.notice') }}</p>
        <p v-if="detail.library_moved" class="rv-notice rv-notice--warn">{{ $t('nexusAgent.review.moved') }}</p>
        <template v-if="detail.scan.findings.length">
          <h5 class="rv-sub">{{ $t('nexusAgent.review.findings') }}</h5>
          <ul class="rv-findings">
            <li v-for="(finding, index) in detail.scan.findings" :key="index">
              <code>{{ finding.path }}{{ finding.line ? `:${finding.line}` : '' }}</code> {{ finding.rule }}
              <span v-if="finding.excerpt" class="rv-excerpt">{{ finding.excerpt }}</span>
            </li>
          </ul>
        </template>
        <h5 class="rv-sub">{{ $t('nexusAgent.review.diff') }}</h5>
        <pre class="rv-pre">{{ detail.diff || $t('nexusAgent.review.noDiff') }}</pre>
        <h5 class="rv-sub">SKILL.md</h5>
        <pre class="rv-pre">{{ detail.skill_md }}</pre>
        <h5 v-if="Object.keys(detail.files).length" class="rv-sub">{{ $t('nexusAgent.review.files') }}</h5>
        <details v-for="(content, path) in detail.files" :key="path" class="rv-file">
          <summary>{{ path }}</summary>
          <pre class="rv-pre">{{ content }}</pre>
        </details>
        <div class="rv-actions">
          <t-popconfirm :content="$t('nexusAgent.review.approveConfirm')" @confirm="decide(true)">
            <t-button theme="primary" :loading="busy" :disabled="busy">{{ $t('nexusAgent.review.approve') }}</t-button>
          </t-popconfirm>
          <t-input v-model="reason" class="rv-reason" :maxlength="1000" :placeholder="$t('nexusAgent.review.reasonPlaceholder')" />
          <t-button theme="danger" variant="outline" :disabled="busy || !reason.trim()" @click="decide(false)">
            {{ $t('nexusAgent.review.reject') }}
          </t-button>
        </div>
      </template>
    </t-loading>
  </t-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  approveSubmission, getSubmissionReview, listReviewQueue, rejectSubmission,
  type SkillSubmission, type SkillSubmissionReview,
} from '@/api/nexus-agents'
import { submissionErrorKey } from './mySkills'
import { parseInstallFailure } from './skillInstall'

const props = defineProps<{ visible: boolean, tenantId: string }>()
const emit = defineEmits<{ (event: 'update:visible', value: boolean): void, (event: 'changed'): void }>()
const { t } = useI18n()

const loading = ref(false)
const busy = ref(false)
const error = ref('')
const queue = ref<SkillSubmission[]>([])
const detail = ref<SkillSubmissionReview | null>(null)
const reason = ref('')

function message(failure: unknown): string {
  const parsed = parseInstallFailure(failure)
  const key = parsed.code ? submissionErrorKey(parsed.code) : ''
  return key && !key.endsWith('.other') ? t(key) : parsed.message || t('nexusAgent.mySkills.failed')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    queue.value = await listReviewQueue(props.tenantId)
  } catch (failure) {
    error.value = message(failure)
  } finally {
    loading.value = false
  }
}

async function openReview(id: string) {
  error.value = ''
  reason.value = ''
  try {
    detail.value = await getSubmissionReview(props.tenantId, id)
  } catch (failure) {
    error.value = message(failure)
  }
}

/** Approve (publishes to the whole space) or reject (the reason is required and reaches the submitter). */
async function decide(approve: boolean) {
  if (!detail.value) return
  busy.value = true
  error.value = ''
  try {
    if (approve) await approveSubmission(props.tenantId, detail.value.id)
    else await rejectSubmission(props.tenantId, detail.value.id, reason.value.trim())
    MessagePlugin.success(t(approve ? 'nexusAgent.review.approved' : 'nexusAgent.review.rejected'))
    detail.value = null
    emit('changed')
  } catch (failure) {
    error.value = message(failure)
    detail.value = null  // a stale or already-decided submission is gone from the queue; show the refreshed list
  } finally {
    busy.value = false
  }
  await load()
}

watch(() => props.visible, (shown) => { if (shown) { detail.value = null; void load() } }, { immediate: true })
</script>

<style scoped>
.rv-alert { margin-bottom: 8px; }
.rv-empty { margin: 0; font-size: var(--app-text-sm); color: var(--td-text-color-secondary); }
.rv-row { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--td-component-stroke); flex-wrap: wrap; }
.rv-name { font-weight: 600; word-break: break-all; }
.rv-spacer { flex: 1; }
.rv-time { font-size: var(--app-text-xs); color: var(--td-text-color-secondary); }
.rv-tag { padding: 0 6px; font-size: var(--app-text-xs); border: 1px solid var(--td-warning-color); color: var(--td-warning-color); border-radius: var(--td-radius-small); }
.rv-tag--muted { border-color: var(--td-component-border); color: var(--td-text-color-secondary); }
.rv-heading { margin: 8px 0; display: flex; align-items: center; gap: 8px; }
.rv-sub { margin: 12px 0 4px; font-size: var(--app-text-sm); }
.rv-notice { margin: 0 0 6px; font-size: var(--app-text-xs); display: flex; align-items: center; gap: 4px; }
.rv-notice--warn { color: var(--td-warning-color); }
.rv-findings { margin: 0; padding-left: 18px; font-size: var(--app-text-xs); line-height: 1.6; max-height: 140px; overflow: auto; }
.rv-excerpt { display: block; color: var(--td-text-color-secondary); font-family: var(--td-font-family-mono, monospace); word-break: break-all; }
.rv-pre { margin: 0; padding: 8px; max-height: 240px; overflow: auto; font-size: var(--app-text-xs); line-height: 1.5; background: var(--td-bg-color-secondarycontainer); border-radius: var(--td-radius-default); white-space: pre-wrap; word-break: break-all; }
.rv-file { margin-top: 6px; font-size: var(--app-text-xs); }
.rv-actions { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.rv-reason { flex: 1; min-width: 160px; }
</style>
