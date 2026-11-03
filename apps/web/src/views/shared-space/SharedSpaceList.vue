<template>
  <main class="shared-space-page">
    <header class="shared-space-header">
      <div>
        <h1>{{ t('sharedSpace.title') }}</h1>
        <p class="shared-space-description">{{ t('sharedSpace.description') }}</p>
      </div>
      <div class="shared-space-actions">
        <t-button variant="outline" @click="openJoinDialog">{{ t('sharedSpace.joinByCode') }}</t-button>
        <t-button theme="primary" :disabled="!currentTenantId" @click="openCreateDialog">
          {{ t('sharedSpace.create') }}
        </t-button>
      </div>
    </header>

    <t-alert v-if="!currentTenantId" theme="warning" :message="t('sharedSpace.noCurrentSpace')" />

    <t-table
      v-else
      row-key="id"
      :data="spaces"
      :columns="columns"
      :loading="loading"
      :empty="t('sharedSpace.empty')"
      @row-click="({ row }: any) => openDetail(row.id)"
    >
      <template #role="{ row }">
        <t-tag v-if="row.role" size="small" variant="light">{{ roleLabel(row.role) }}</t-tag>
      </template>
      <template #owner="{ row }">
        <t-tag v-if="row.owner_tenant_id === currentTenantId" size="small" theme="primary" variant="light">
          {{ t('sharedSpace.createdByMe') }}
        </t-tag>
      </template>
    </t-table>

    <!-- Create -->
    <t-dialog v-model:visible="createVisible" :header="t('sharedSpace.create')" :confirm-btn="t('common.confirm')"
      :cancel-btn="t('common.cancel')" :confirm-loading="saving" @confirm="submitCreate">
      <t-form :data="createForm" label-align="top">
        <t-form-item :label="t('sharedSpace.name')" name="name">
          <t-input v-model="createForm.name" maxlength="160" />
        </t-form-item>
        <t-form-item :label="t('sharedSpace.descriptionLabel')" name="description">
          <t-textarea v-model="createForm.description" :autosize="{ minRows: 2, maxRows: 4 }" />
        </t-form-item>
      </t-form>
    </t-dialog>

    <!-- Join by invite code -->
    <t-dialog v-model:visible="joinVisible" :header="t('sharedSpace.joinByCode')" :footer="false" width="460px">
      <t-form label-align="top">
        <t-form-item :label="t('sharedSpace.inviteCode')">
          <t-input v-model="joinCode" :placeholder="t('sharedSpace.inviteCodePlaceholder')" />
        </t-form-item>
        <t-form-item v-if="preview" :label="t('sharedSpace.preview')">
          <div class="shared-space-preview">
            <strong>{{ preview.name }}</strong>
            <span>{{ t('sharedSpace.memberCount', { count: preview.member_count }) }}</span>
            <span v-if="preview.require_approval">{{ t('sharedSpace.requiresApproval') }}</span>
          </div>
        </t-form-item>
        <div class="shared-space-dialog-actions">
          <t-button variant="outline" :disabled="!joinCode.trim()" @click="previewCode">
            {{ t('sharedSpace.preview') }}
          </t-button>
          <t-button theme="primary" :disabled="!joinCode.trim()" :loading="saving" @click="submitJoin">
            {{ t('sharedSpace.join') }}
          </t-button>
        </div>
      </t-form>
    </t-dialog>

    <!-- Reject a join request -->
    <t-dialog v-model:visible="rejectVisible" :header="t('sharedSpace.rejectReason')"
      :confirm-btn="t('sharedSpace.reject')" :cancel-btn="t('common.cancel')" :confirm-loading="saving"
      :confirm-disabled="!rejectReason.trim()" @confirm="submitReject">
      <t-textarea v-model="rejectReason" :autosize="{ minRows: 2, maxRows: 4 }" />
    </t-dialog>

    <!-- Detail and settings -->
    <t-dialog v-model:visible="detailVisible" :header="detail?.name || t('sharedSpace.title')" :footer="false" width="720px">
      <template v-if="detail">
        <section class="shared-space-section">
          <h3>{{ t('sharedSpace.members') }}</h3>
          <t-table row-key="tenant_id" size="small" :data="detail.members" :columns="memberColumns">
            <template #role="{ row }">{{ roleLabel(row.role) }}</template>
          </t-table>
        </section>

        <section v-if="isAdmin" class="shared-space-section">
          <h3>{{ t('sharedSpace.settings') }}</h3>
          <t-form :data="settingsForm" label-align="left" label-width="160px">
            <t-form-item :label="t('sharedSpace.requireApproval')">
              <t-switch v-model="settingsForm.require_approval" />
            </t-form-item>
            <t-form-item :label="t('sharedSpace.searchable')">
              <t-switch v-model="settingsForm.searchable" />
            </t-form-item>
            <t-form-item :label="t('sharedSpace.memberLimit')">
              <t-input-number v-model="settingsForm.member_limit" :min="1" :max="10000" />
            </t-form-item>
            <t-form-item :label="t('sharedSpace.inviteCodeDays')">
              <t-input-number v-model="settingsForm.invite_code_validity_days" :min="1" :max="365" />
            </t-form-item>
            <t-button theme="primary" :loading="saving" @click="saveSettings">{{ t('common.save') }}</t-button>
          </t-form>
          <div class="shared-space-invite">
            <span>{{ t('sharedSpace.inviteCode') }}: </span>
            <code>{{ detail.invite_code || t('sharedSpace.noInviteCode') }}</code>
            <t-button size="small" variant="outline" @click="newInviteCode">{{ t('sharedSpace.regenerate') }}</t-button>
          </div>
        </section>

        <section v-if="isAdmin" class="shared-space-section">
          <h3>{{ t('sharedSpace.pendingRequests') }}</h3>
          <t-table row-key="id" size="small" :data="joinRequests" :columns="requestColumns"
            :empty="t('sharedSpace.noRequests')">
            <template #kind="{ row }">
              {{ row.request_type === 'upgrade' ? t('sharedSpace.upgradeRequest') : t('sharedSpace.joinRequest') }}
            </template>
            <template #requested="{ row }">{{ roleLabel(row.requested_role) }}</template>
            <template #actions="{ row }">
              <t-space size="small">
                <t-button size="small" theme="primary" @click="approve(row.id)">{{ t('sharedSpace.approve') }}</t-button>
                <t-button size="small" variant="outline" theme="danger" @click="openReject(row.id)">
                  {{ t('sharedSpace.reject') }}
                </t-button>
              </t-space>
            </template>
          </t-table>
        </section>

        <section class="shared-space-section shared-space-footer">
          <t-button v-if="!isOwnerSpace" variant="outline" @click="leave">{{ t('sharedSpace.leave') }}</t-button>
          <t-button v-if="isOwnerSpace" variant="outline" theme="danger" @click="removeSpace">
            {{ t('sharedSpace.delete') }}
          </t-button>
        </section>
      </template>
    </t-dialog>
  </main>
</template>

<script setup lang="ts">
// Shared spaces: list, create, join by invite code, and settings for admins of the shared space.
// The acting space is the caller's current space (X-Tenant-ID). Business rules are in the backend.
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { takePendingInviteCode } from '@/utils/pendingInvite'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@/stores/auth'
import {
  approveJoinRequest, createSharedSpace, deleteSharedSpace, getSharedSpace, joinByInviteCode, leaveSharedSpace,
  listJoinRequests, listSharedSpaces, previewInviteCode, regenerateInviteCode, rejectJoinRequest,
  type SharedRole, type SharedSpaceDetail, type SharedSpaceJoinRequest, type SharedSpaceSummary,
  updateSharedSpace,
} from '@/api/shared-space'

const { t } = useI18n()
const authStore = useAuthStore()

const currentTenantId = computed(() => authStore.effectiveTenantId ?? '')
const spaces = ref<SharedSpaceSummary[]>([])
const loading = ref(false)
const saving = ref(false)

const createVisible = ref(false)
const createForm = reactive({ name: '', description: '' })

const joinVisible = ref(false)
const joinCode = ref('')
const preview = ref<{ name: string; member_count: number; require_approval: boolean } | null>(null)

const detailVisible = ref(false)
const detail = ref<SharedSpaceDetail | null>(null)
const joinRequests = ref<SharedSpaceJoinRequest[]>([])
const settingsForm = reactive({
  require_approval: false, searchable: false, member_limit: 50, invite_code_validity_days: 7,
})

const rejectVisible = ref(false)
const rejectTargetId = ref('')
const rejectReason = ref('')

const isAdmin = computed(() => detail.value?.role === 'admin')
const isOwnerSpace = computed(() => !!detail.value && detail.value.owner_tenant_id === currentTenantId.value)

const roleLabel = (role: SharedRole) => t(`sharedSpace.roles.${role}`)

const columns = computed(() => [
  { colKey: 'name', title: t('sharedSpace.name'), ellipsis: true },
  { colKey: 'role', title: t('sharedSpace.myRole'), width: 120 },
  { colKey: 'member_count', title: t('sharedSpace.members'), width: 100 },
  { colKey: 'owner', title: '', width: 120 },
])
const memberColumns = computed(() => [
  { colKey: 'tenant_name', title: t('sharedSpace.spaceName') },
  { colKey: 'role', title: t('sharedSpace.myRole'), width: 120 },
])
const requestColumns = computed(() => [
  { colKey: 'tenant_name', title: t('sharedSpace.spaceName') },
  { colKey: 'kind', title: t('sharedSpace.requestKind'), width: 110 },
  { colKey: 'requested', title: t('sharedSpace.requestedRole'), width: 110 },
  { colKey: 'message', title: t('sharedSpace.message'), ellipsis: true },
  { colKey: 'actions', title: '', width: 160 },
])

const errorMessage = (error: any) => error?.message || error?.error?.message || t('sharedSpace.failed')

const load = async () => {
  if (!currentTenantId.value) return
  loading.value = true
  try {
    spaces.value = await listSharedSpaces().then((rows: any) => rows ?? [])
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

const openCreateDialog = () => {
  createForm.name = ''
  createForm.description = ''
  createVisible.value = true
}

const submitCreate = async () => {
  if (!createForm.name.trim()) {
    MessagePlugin.warning(t('sharedSpace.nameRequired'))
    return
  }
  saving.value = true
  try {
    await createSharedSpace({ name: createForm.name.trim(), description: createForm.description.trim() })
    createVisible.value = false
    MessagePlugin.success(t('sharedSpace.created'))
    await load()
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

const openJoinDialog = () => {
  joinCode.value = ''
  preview.value = null
  joinVisible.value = true
}

const previewCode = async () => {
  try {
    preview.value = await previewInviteCode(joinCode.value.trim())
  } catch (error) {
    preview.value = null
    MessagePlugin.error(errorMessage(error))
  }
}

const submitJoin = async () => {
  saving.value = true
  try {
    const result = await joinByInviteCode(joinCode.value.trim())
    joinVisible.value = false
    MessagePlugin.success(result.status === 'pending' ? t('sharedSpace.requestSent') : t('sharedSpace.joined'))
    await load()
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

const loadDetail = async (id: string) => {
  detail.value = await getSharedSpace(id)
  settingsForm.require_approval = detail.value.require_approval
  settingsForm.searchable = detail.value.searchable
  settingsForm.member_limit = detail.value.member_limit
  settingsForm.invite_code_validity_days = detail.value.invite_code_validity_days
  joinRequests.value = detail.value.role === 'admin' ? await listJoinRequests(id) : []
}

const openDetail = async (id: string) => {
  try {
    await loadDetail(id)
    detailVisible.value = true
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  }
}

const saveSettings = async () => {
  if (!detail.value) return
  saving.value = true
  try {
    await updateSharedSpace(detail.value.id, { ...settingsForm })
    MessagePlugin.success(t('sharedSpace.saved'))
    await loadDetail(detail.value.id)
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

const newInviteCode = async () => {
  if (!detail.value) return
  try {
    await regenerateInviteCode(detail.value.id)
    await loadDetail(detail.value.id)
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  }
}

const approve = async (requestId: string) => {
  if (!detail.value) return
  try {
    await approveJoinRequest(detail.value.id, requestId)
    await loadDetail(detail.value.id)
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  }
}

const openReject = (requestId: string) => {
  rejectTargetId.value = requestId
  rejectReason.value = ''
  rejectVisible.value = true
}

const submitReject = async () => {
  if (!detail.value || !rejectTargetId.value) return
  saving.value = true
  try {
    await rejectJoinRequest(detail.value.id, rejectTargetId.value, rejectReason.value.trim())
    rejectVisible.value = false
    await loadDetail(detail.value.id)
  } catch (error) {
    MessagePlugin.error(errorMessage(error))
  } finally {
    saving.value = false
  }
}

const leave = () => {
  if (!detail.value) return
  const id = detail.value.id
  DialogPlugin.confirm({
    header: t('sharedSpace.leaveConfirm'),
    onConfirm: async () => {
      try {
        await leaveSharedSpace(id)
        detailVisible.value = false
        await load()
      } catch (error) {
        MessagePlugin.error(errorMessage(error))
      }
    },
  })
}

const removeSpace = () => {
  if (!detail.value) return
  const id = detail.value.id
  DialogPlugin.confirm({
    header: t('sharedSpace.deleteConfirm'),
    onConfirm: async () => {
      try {
        await deleteSharedSpace(id)
        detailVisible.value = false
        await load()
      } catch (error) {
        MessagePlugin.error(errorMessage(error))
      }
    },
  })
}

// `/join?code=...` lands here with `invite_code` (or with the code kept across sign-in): open the join dialog
// with the code filled in and preview it, so the user only confirms.
const route = useRoute()
onMounted(async () => {
  await load()
  const fromQuery = typeof route.query.invite_code === 'string' ? route.query.invite_code : ''
  const code = (fromQuery || takePendingInviteCode()).trim()
  if (!code) return
  openJoinDialog()
  joinCode.value = code
  await previewCode()
})
</script>

<style scoped lang="less">
.shared-space-page {
  padding: 24px;
}

.shared-space-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.shared-space-description {
  color: var(--td-text-color-secondary);
  margin-top: 4px;
}

.shared-space-actions,
.shared-space-dialog-actions,
.shared-space-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.shared-space-section {
  margin-top: 16px;

  h3 {
    margin-bottom: 8px;
  }
}

.shared-space-preview {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shared-space-invite {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}
</style>
