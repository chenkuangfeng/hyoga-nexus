<script setup lang="ts">
/** 企业技能审核队列；投稿正文、文件、扫描摘录和差异全部按纯文本显示。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { approveEnterpriseSkillSubmission, getEnterpriseSkillSubmission, listEnterpriseSkillSubmissions, rejectEnterpriseSkillSubmission, type SkillSubmissionDetail, type SkillSubmissionRow } from '@nexus-web/core/api/enterprise-skill-submissions'
import { useEnterpriseContext } from '../../stores/context'

const { t } = useI18n(), auth = useAuthStore(), context = useEnterpriseContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('tools:manage'))
const rows = ref<SkillSubmissionRow[]>([]), selected = ref<SkillSubmissionDetail | null>(null), selectedId = ref(''), ready = ref(false), loading = ref(false), detailLoading = ref(false), busy = ref(false), error = ref(''), reason = ref(''), rejecting = ref(false)
let epoch = 0, detailEpoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
function clearDetail() { detailEpoch++; selected.value = null; selectedId.value = ''; detailLoading.value = false; reason.value = ''; rejecting.value = false }
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; ready.value = false; loading.value = false; busy.value = false; error.value = ''; clearDetail() }
async function load() {
  const current = ++epoch, scope = tenant.value; confirmation?.hide(); confirmation = undefined; clearDetail(); rows.value = []; ready.value = false; error.value = ''
  if (!scope || !canManage.value) return
  loading.value = true
  try { const result = await listEnterpriseSkillSubmissions(scope); if (current === epoch) { rows.value = result; ready.value = true } }
  catch { if (current === epoch) error.value = t('adminSkillReview.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
async function inspect(row: SkillSubmissionRow) {
  if (!canManage.value || !ready.value || busy.value || !rows.value.includes(row)) return
  const current = epoch, target = ++detailEpoch, scope = tenant.value; selectedId.value = row.id; selected.value = null; detailLoading.value = true; error.value = ''; rejecting.value = false; reason.value = ''
  try { const result = await getEnterpriseSkillSubmission(scope, row.id); if (current === epoch && target === detailEpoch && result.id === row.id) selected.value = result }
  catch { if (current === epoch && target === detailEpoch) error.value = t('adminSkillReview.detailFailed') }
  finally { if (current === epoch && target === detailEpoch) detailLoading.value = false }
}
function confirmApprove() {
  const detail = selected.value
  if (!detail || !canManage.value || busy.value || detail.state !== 'pending' || confirmation) return
  const current = epoch, target = detailEpoch, scope = tenant.value, id = detail.id
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminSkillReview.approveTitle'), body: t('adminSkillReview.approveConfirm', { name: detail.name }), theme: 'warning',
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (current !== epoch || target !== detailEpoch || !canManage.value || busy.value) return
      busy.value = true; error.value = ''
      try { await approveEnterpriseSkillSubmission(scope, id); if (current !== epoch || target !== detailEpoch) return
        rows.value = rows.value.filter(row => row.id !== id); clearDetail(); MessagePlugin.success(t('adminSkillReview.approved'))
      } catch { if (current === epoch && target === detailEpoch) error.value = t('adminSkillReview.approveFailed') }
      finally { if (current === epoch) busy.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
async function reject() {
  const detail = selected.value
  if (!detail || !canManage.value || busy.value || !reason.value.trim() || reason.value.trim().length > 1000 || detail.state !== 'pending') return
  const current = epoch, target = detailEpoch, scope = tenant.value, id = detail.id; busy.value = true; error.value = ''
  try { await rejectEnterpriseSkillSubmission(scope, id, reason.value.trim()); if (current !== epoch || target !== detailEpoch) return
    rows.value = rows.value.filter(row => row.id !== id); clearDetail(); MessagePlugin.success(t('adminSkillReview.rejected'))
  } catch { if (current === epoch && target === detailEpoch) error.value = t('adminSkillReview.rejectFailed') }
  finally { if (current === epoch) busy.value = false }
}
</script>

<template>
  <section class="skill-review-page">
    <header class="section-header"><div><h2>{{ t('adminSkillReview.title') }}</h2><p>{{ t('adminSkillReview.description') }}</p></div><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-alert theme="info" :message="t('adminSkillReview.scopeHint')" />
      <div class="review-layout"><t-loading :loading="loading"><section v-if="ready" class="queue"><h3>{{ t('adminSkillReview.queue') }}</h3><button v-for="row in rows" :key="row.id" type="button" class="queue-item" :class="{ active: selectedId === row.id }" :disabled="busy" @click="inspect(row)"><strong>{{ row.name }}</strong><span>{{ row.description || t('adminSkillReview.noDescription') }}</span><small>{{ row.created_at }} · {{ row.verdict }} · {{ t('adminSkillReview.findingCount', { count: row.findings }) }}</small></button><div v-if="!rows.length" class="empty">{{ t('adminSkillReview.empty') }}</div></section></t-loading>
        <section v-if="selectedId" class="detail"><t-loading :loading="detailLoading"><template v-if="selected"><header class="detail-header"><div><h3>{{ selected.name }}</h3><p>{{ selected.description }}</p></div><div class="actions"><t-tag :theme="selected.scan.verdict === 'safe' ? 'success' : 'warning'" variant="light">{{ selected.scan.verdict }}</t-tag><t-button variant="text" :disabled="busy" @click="clearDetail">{{ t('common.close') }}</t-button></div></header><p class="notice">{{ selected.notice }}</p><t-alert v-if="selected.library_moved" theme="warning" :message="t('adminSkillReview.libraryMoved')" />
          <h4>{{ t('adminSkillReview.scanFindings') }} <span>{{ selected.scan.findings.length }}</span></h4><div v-for="(finding, index) in selected.scan.findings" :key="`${finding.rule}-${index}`" class="finding"><strong>{{ finding.severity }} · {{ finding.rule }}</strong><code>{{ finding.path }}<span v-if="finding.line !== null">:{{ finding.line }}</span></code><pre>{{ finding.excerpt }}</pre></div><div v-if="!selected.scan.findings.length" class="empty-inline">{{ t('adminSkillReview.noFindings') }}</div>
          <details><summary>{{ t('adminSkillReview.skillText') }}</summary><pre class="plain-text">{{ selected.skill_md }}</pre></details><details v-for="(content, path) in selected.files" :key="path"><summary>{{ path }}</summary><pre class="plain-text">{{ content }}</pre></details><details open><summary>{{ t('adminSkillReview.diff') }}</summary><pre class="plain-text diff">{{ selected.diff }}</pre></details>
          <section v-if="selected.state === 'pending'" class="decision"><div class="actions"><t-button theme="primary" :disabled="busy || selected.library_moved" @click="confirmApprove">{{ t('adminSkillReview.approve') }}</t-button><t-button theme="danger" variant="outline" :disabled="busy || rejecting" @click="rejecting = true">{{ t('adminSkillReview.reject') }}</t-button></div><p v-if="selected.library_moved" class="warn-text">{{ t('adminSkillReview.libraryMovedHint') }}</p><div v-if="rejecting" class="reject-box"><label>{{ t('adminSkillReview.rejectReason') }}<t-textarea v-model="reason" :maxlength="1000" :autosize="{ minRows: 3, maxRows: 6 }" :disabled="busy" /></label><div class="actions"><t-button variant="text" :disabled="busy" @click="rejecting = false; reason = ''">{{ t('common.cancel') }}</t-button><t-button theme="danger" :loading="busy" :disabled="busy || !reason.trim()" @click="reject">{{ t('adminSkillReview.confirmReject') }}</t-button></div></div></section>
        </template></t-loading></section><div v-else-if="ready && !selectedId" class="detail-placeholder">{{ t('adminSkillReview.chooseSubmission') }}</div></div>
    </template>
  </section>
</template>

<style scoped>
.skill-review-page { min-width: 0; }
.review-layout { display: grid; grid-template-columns: minmax(260px, 340px) minmax(0, 1fr); gap: 20px; margin-top: 20px; align-items: start; }
.queue, .detail, .detail-placeholder { min-width: 0; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.queue h3, .detail h3 { margin: 0 0 14px; }
.queue-item { display: grid; width: 100%; gap: 6px; text-align: left; padding: 12px; margin: 0 0 8px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); background: transparent; color: var(--td-text-color-primary); cursor: pointer; }
.queue-item:hover, .queue-item.active { border-color: var(--td-brand-color); background: var(--td-bg-color-secondarycontainer); }
.queue-item span, .queue-item small, .detail-header p, .notice { color: var(--td-text-color-secondary); overflow-wrap: anywhere; }
.detail-header, .actions { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.detail-header h3 { overflow-wrap: anywhere; }
.detail h4 { margin: 20px 0 10px; }
.finding { margin: 8px 0; padding: 12px; border-left: 3px solid var(--td-warning-color); background: var(--td-bg-color-secondarycontainer); }
.finding strong, .finding code { display: block; overflow-wrap: anywhere; }
.finding pre, .plain-text { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.55; }
.plain-text { max-height: 420px; overflow: auto; padding: 12px; background: var(--td-bg-color-secondarycontainer); }
.diff { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: var(--app-text-sm); }
details { margin: 16px 0; }
summary { cursor: pointer; font-weight: 600; }
.decision, .reject-box { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--td-component-stroke); }
.reject-box label { display: grid; gap: 8px; margin-bottom: 12px; }
.warn-text { color: var(--td-warning-color); }
.empty, .empty-inline, .detail-placeholder { color: var(--td-text-color-secondary); }
.detail-placeholder { min-height: 200px; display: grid; place-items: center; }
@media (max-width: 900px) { .review-layout { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 600px) { .queue, .detail { padding: 16px; } .detail-header { flex-direction: column; } }
</style>
