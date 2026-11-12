<template>
  <div class="join-applications">
    <t-alert v-if="loadError" theme="error" :message="loadError">
      <template #operation>
        <t-button size="small" @click="load">{{ t('tenantApplication.retry') }}</t-button>
      </template>
    </t-alert>

    <div v-else-if="!loading && applications.length === 0" class="empty-state">
      <t-empty :description="t('tenantApplication.empty')" />
    </div>

    <t-table v-else row-key="id" :data="applications" :columns="columns" size="medium" hover :loading="loading">
      <template #applicant="{ row }">
        <span>{{ row.display_name || row.email || row.user_id }}</span>
        <span v-if="row.email" class="applicant-email">{{ row.email }}</span>
      </template>
      <template #message="{ row }">{{ row.message || '-' }}</template>
      <template #created_at="{ row }">{{ formatDate(row.created_at) }}</template>
      <template #operation="{ row }">
        <t-space size="small">
          <t-button size="small" theme="primary" variant="text" @click="openApprove(row)">
            {{ t('tenantApplication.approve') }}
          </t-button>
          <t-button size="small" theme="danger" variant="text" @click="openReject(row)">
            {{ t('tenantApplication.reject') }}
          </t-button>
        </t-space>
      </template>
    </t-table>

    <t-dialog v-model:visible="approveVisible" :header="t('tenantApplication.approveTitle')"
      :confirm-btn="{ content: t('tenantApplication.approve'), theme: 'primary', loading: submitting }"
      :cancel-btn="t('tenantApplication.cancel')" width="460px" @confirm="submitApprove">
      <t-form label-align="top">
        <t-form-item :label="t('tenantApplication.unitLabel')">
          <t-select v-model="approveUnitId" :options="unitOptions" :placeholder="t('tenantApplication.unitPlaceholder')"
            filterable clearable />
        </t-form-item>
        <t-form-item :label="t('tenantApplication.roleLabel')">
          <t-select v-model="approveRole" :options="roleOptions" />
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog v-model:visible="rejectVisible" :header="t('tenantApplication.rejectTitle')"
      :confirm-btn="{ content: t('tenantApplication.reject'), theme: 'danger', loading: submitting }"
      :cancel-btn="t('tenantApplication.cancel')" width="460px" @confirm="submitReject">
      <t-form label-align="top">
        <t-form-item :label="t('tenantApplication.reasonLabel')">
          <t-textarea v-model="rejectReason" :maxlength="500" :autosize="{ minRows: 3, maxRows: 6 }" />
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup lang="ts">
// 企业的加入申请审批：列出待处理申请，批准时必须选部门与角色，拒绝时必须填写原因。
// 后端负责权限（members:manage）与状态校验；这里只做表单必填检查并在成功后通知父组件刷新成员列表。
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  approveJoinApplication,
  listJoinApplications,
  rejectJoinApplication,
  type ApplicationRole,
  type JoinApplication,
} from '@nexus-web/core/api/tenant/applications'
import { flattenOrgUnits, getOrgUnitTree } from '@nexus-web/core/api/tenant/org-units'

const props = defineProps<{ tenantId: string }>()
const emit = defineEmits<{ (e: 'changed'): void }>()
const { t, locale } = useI18n()

const applications = ref<JoinApplication[]>([])
const loading = ref(false)
const loadError = ref('')
const submitting = ref(false)
const unitOptions = ref<Array<{ label: string; value: string }>>([])

const approveVisible = ref(false)
const approveTarget = ref<JoinApplication | null>(null)
const approveUnitId = ref<string | undefined>(undefined)
const approveRole = ref<ApplicationRole>('contributor')

const rejectVisible = ref(false)
const rejectTarget = ref<JoinApplication | null>(null)
const rejectReason = ref('')

const roleOptions = computed(() => [
  { label: t('tenantApplication.roles.admin'), value: 'admin' },
  { label: t('tenantApplication.roles.contributor'), value: 'contributor' },
  { label: t('tenantApplication.roles.viewer'), value: 'viewer' },
])

const columns = computed(() => [
  { colKey: 'applicant', title: t('tenantApplication.columns.applicant'), ellipsis: true },
  { colKey: 'message', title: t('tenantApplication.columns.message'), ellipsis: true },
  { colKey: 'created_at', title: t('tenantApplication.columns.appliedAt'), width: 180 },
  { colKey: 'operation', title: t('tenantApplication.columns.operation'), width: 160 },
])

function formatDate(s: string | undefined): string {
  if (!s) return '-'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? s : new Intl.DateTimeFormat(locale.value || 'zh-CN', {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(d)
}

function errorText(error: unknown): string {
  return (error as { message?: string })?.message || t('tenantApplication.failed')
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    applications.value = await listJoinApplications(props.tenantId)
  } catch (error) {
    loadError.value = errorText(error)
  } finally {
    loading.value = false
  }
}

async function loadUnits() {
  try {
    unitOptions.value = flattenOrgUnits(await getOrgUnitTree(props.tenantId))
  } catch (error) {
    unitOptions.value = []
    MessagePlugin.error(errorText(error))
  }
}

function openApprove(row: JoinApplication) {
  approveTarget.value = row
  approveUnitId.value = undefined
  approveRole.value = 'contributor'
  approveVisible.value = true
}

async function submitApprove() {
  if (!approveTarget.value) return
  if (!approveUnitId.value) {
    MessagePlugin.warning(t('tenantApplication.unitRequired'))
    return
  }
  submitting.value = true
  try {
    await approveJoinApplication(props.tenantId, approveTarget.value.id, {
      unit_id: approveUnitId.value,
      role: approveRole.value,
    })
    approveVisible.value = false
    MessagePlugin.success(t('tenantApplication.approved'))
    await load()
    emit('changed')
  } catch (error) {
    MessagePlugin.error(errorText(error))
  } finally {
    submitting.value = false
  }
}

function openReject(row: JoinApplication) {
  rejectTarget.value = row
  rejectReason.value = ''
  rejectVisible.value = true
}

async function submitReject() {
  if (!rejectTarget.value) return
  const reason = rejectReason.value.trim()
  if (!reason) {
    MessagePlugin.warning(t('tenantApplication.reasonRequired'))
    return
  }
  submitting.value = true
  try {
    await rejectJoinApplication(props.tenantId, rejectTarget.value.id, reason)
    rejectVisible.value = false
    MessagePlugin.success(t('tenantApplication.rejected'))
    await load()
  } catch (error) {
    MessagePlugin.error(errorText(error))
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void load()
  void loadUnits()
})

// Switching space changes which applications and departments are listed.
watch(() => props.tenantId, () => {
  void load()
  void loadUnits()
})
</script>

<style scoped lang="less">
.join-applications {
  min-height: 120px;
}

.applicant-email {
  display: block;
  color: var(--td-text-color-secondary);
  font-size: var(--app-text-sm);
}

.empty-state {
  padding: 32px 0;
}
</style>
