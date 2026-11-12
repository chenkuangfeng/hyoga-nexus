<template>
  <div class="share-to-space-panel">
    <div class="share-panel-header">
      <div class="share-panel-header-row">
        <div class="share-panel-titlewrap">
          <h2 class="share-panel-title">{{ $t('organization.share.title') }}</h2>
          <t-popup placement="bottom-start" trigger="hover" overlay-class-name="wk-popover share-hint-popup-overlay"
            :overlay-inner-style="shareHintPopupInnerStyle">
            <button type="button" class="share-hint-trigger-btn" :aria-label="$t('agent.shareScope.title')"
              :title="$t('agent.shareScope.title')">
              <t-icon name="info-circle" size="16px" />
            </button>
            <template #content>
              <div class="share-hint-popover">
                <p class="share-hint-title">{{ $t('agent.shareScope.title') }}</p>
                <p class="share-hint-desc">{{ $t('organization.share.agentShareDesc') }}</p>
                <p v-if="agent?.config" class="share-hint-desc">{{ $t('agent.shareScope.desc') }}</p>
              </div>
            </template>
          </t-popup>
        </div>
      </div>
      <p class="share-panel-desc">{{ $t('organization.share.agentShareDesc') }}</p>
      <t-alert v-if="sharesSkillSecrets" theme="warning" class="share-panel-alert"
        :message="$t('agent.shareScope.skillSecretsWarning')" />
    </div>

    <div class="share-panel-list-wrap">
      <div class="share-panel-list-header">
        <div class="share-panel-titlewrap">
          <span class="share-panel-list-title">{{ $t('organization.share.sharedTo') }}</span>
          <span class="share-panel-count-badge">{{ filteredShares.length }}</span>
        </div>
        <div class="share-panel-actions">
          <div class="share-panel-search">
            <t-input v-model="searchQuery" size="small" :placeholder="$t('organization.share.searchPlaceholder')"
              clearable>
              <template #prefix-icon>
                <t-icon name="search" />
              </template>
            </t-input>
          </div>
          <t-popup v-model="addPopupVisible" trigger="click" placement="bottom-end" destroy-on-close
            overlay-class-name="share-add-popup-overlay">
            <t-button theme="primary" variant="outline" shape="square" size="small" class="share-panel-add-btn"
              :title="$t('knowledgeEditor.share.addShare')" :aria-label="$t('knowledgeEditor.share.addShare')">
              <template #icon><t-icon name="add" /></template>
            </t-button>
            <template #content>
              <div class="share-add-popup-inner" @click.stop>
                <div class="member-invite-popup-title">{{ $t('organization.share.addShareDialogTitle') }}</div>
                <div class="org-upgrade-fields">
                  <div class="org-upgrade-field">
                    <label class="org-upgrade-field-label">{{ $t('organization.share.selectOrg') }}</label>
                    <t-select v-model="selectedSpaceId" :loading="loadingSpaces"
                      :placeholder="$t('organization.share.selectOrgPlaceholder')">
                      <t-option v-for="space in availableSpaces" :key="space.id" :value="space.id"
                        :label="space.name" />
                    </t-select>
                  </div>
                  <div class="org-upgrade-field org-upgrade-field--last">
                    <label class="org-upgrade-field-label">{{ $t('organization.share.levelLabel') }}</label>
                    <t-select v-model="selectedLevel" :options="levelOptions" />
                  </div>
                </div>
                <div class="invite-popup-footer">
                  <t-button variant="outline" :disabled="submitting" @click="addPopupVisible = false">
                    {{ $t('common.cancel') }}
                  </t-button>
                  <t-button theme="primary" :loading="submitting" :disabled="!selectedSpaceId" @click="handleShare">
                    {{ $t('knowledgeEditor.share.addShare') }}
                  </t-button>
                </div>
              </div>
            </template>
          </t-popup>
        </div>
      </div>

      <t-alert v-if="!canManageShares" theme="info" class="share-panel-alert"
        :message="$t('organization.share.enterpriseOnly')" />
      <div v-else-if="loadingShares && shares.length === 0" class="share-panel-loading">
        <t-loading size="small" />
        <span>{{ $t('organization.share.loading') }}</span>
      </div>
      <div v-else-if="filteredShares.length === 0" class="share-panel-empty">
        <t-empty :description="searchQuery.trim()
          ? $t('organization.share.emptySearch', { q: searchQuery })
          : $t('organization.share.noShares')" />
      </div>
      <div v-else class="share-panel-table-shell">
        <t-table row-key="id" :data="filteredShares" :columns="shareColumns" size="medium" hover stripe
          :loading="loadingShares">
          <template #space="{ row }">
            <div class="share-space-cell">
              <span class="share-space-name">
                <SpaceAvatar :name="row.shared_space_name || ''" size="small" />
                <span class="share-space-name-text">{{ row.shared_space_name }}</span>
              </span>
            </div>
          </template>
          <template #permission="{ row }">
            <t-select :model-value="row.level" :options="levelOptions" size="small" :clearable="false"
              :disabled="!canManageShares" @change="(value: AgentShareLevel) => handleLevelChange(row, value)" />
          </template>
          <template #created_at="{ row }">{{ formatShareDate(row.created_at) }}</template>
          <template #actions="{ row }">
            <div class="share-table-actions">
              <t-popconfirm :content="$t('knowledgeEditor.share.unshareConfirm', { name: row.shared_space_name })"
                :confirm-btn="{ content: $t('common.confirm'), theme: 'danger' }"
                :cancel-btn="{ content: $t('common.cancel') }" placement="left" @confirm="handleUnshare(row)">
                <t-tooltip :content="$t('organization.share.unshareAction')" placement="top">
                  <t-button theme="danger" shape="square" variant="text" size="small" @click.stop>
                    <template #icon><t-icon name="delete" /></template>
                  </t-button>
                </t-tooltip>
              </t-popconfirm>
            </div>
          </template>
        </t-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { listSharedSpaces } from '@nexus-web/core/api/shared-space/index'
import type { SharedSpaceSummary } from '@nexus-web/core/api/shared-space/index'
import {
  listAgentShares,
  shareAgent,
  unshareAgent,
} from '@nexus-web/core/api/agent-share/index'
import type { AgentShare, AgentShareLevel } from '@nexus-web/core/api/agent-share/index'
import type { CustomAgent } from '@nexus-web/core/api/agent/index'
import SpaceAvatar from '@/components/SpaceAvatar.vue'

const { t } = useI18n()
const authStore = useAuthStore()

interface Props {
  agentId: string
  agent?: CustomAgent | null
}

const props = defineProps<Props>()

/**
 * 智能体共享只在企业空间内由 owner/admin 管理（后端 `is_space_manager`）；
 * 个人空间没有共享入口，因此这里不发起请求，只提示。
 */
const currentTenantId = computed(() => authStore.currentTenantId ?? '')
const canManageShares = computed(() => {
  const membership = authStore.memberships.find(m => String(m.tenant_id) === currentTenantId.value)
  return membership?.kind === 'enterprise' && (membership.role === 'owner' || membership.role === 'admin')
})

// Members run this agent's skills in this workspace's sandbox, with the
// environment values its admins configured for them, and can have the model
// print those values. Sharing stays allowed; the owner is told before sharing.
const sharesSkillSecrets = computed(() => {
  const config = props.agent?.config
  if (!config?.sandbox_config_id) return false
  return config.skills_selection_mode === 'all'
    || (config.skills_selection_mode === 'selected' && (config.selected_skills?.length ?? 0) > 0)
})

const shareHintPopupInnerStyle = {
  boxSizing: 'border-box' as const,
  padding: '0',
  width: 'min(400px, calc(100vw - 24px))',
  maxWidth: 'min(400px, calc(100vw - 24px))',
  maxHeight: 'min(280px, 65vh)',
  overflow: 'hidden',
}

const loadingSpaces = ref(false)
const loadingShares = ref(false)
const submitting = ref(false)
const addPopupVisible = ref(false)
const searchQuery = ref('')
const selectedSpaceId = ref('')
const selectedLevel = ref<AgentShareLevel>('viewer')
const shares = ref<AgentShare[]>([])
const sharedSpaces = ref<SharedSpaceSummary[]>([])

const levelOptions = computed(() => [
  { value: 'viewer', label: t('organization.share.level.viewer') },
  { value: 'editor', label: t('organization.share.level.editor') },
  { value: 'admin', label: t('organization.share.level.admin') },
])

// Shared spaces this enterprise is a member of that do not yet carry this agent.
const availableSpaces = computed(() => {
  const sharedIds = new Set(shares.value.map(s => s.shared_space_id))
  return sharedSpaces.value.filter(space => !sharedIds.has(space.id))
})

const filteredShares = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return shares.value
  return shares.value.filter(share => share.shared_space_name.toLowerCase().includes(query))
})

const shareColumns = computed(() => [
  { colKey: 'space', title: t('organization.share.columns.space'), ellipsis: true, minWidth: 180 },
  { colKey: 'permission', title: t('organization.share.columns.permission'), width: 120 },
  { colKey: 'created_at', title: t('organization.share.columns.sharedAt'), width: 154 },
  { colKey: 'actions', title: t('organization.share.columns.operations'), width: 72, align: 'left' },
])

function formatShareDate(dateStr?: string) {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return dateStr
  return date.toLocaleDateString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function errorMessage(e: unknown, fallback: string) {
  return e instanceof Error && e.message ? e.message : fallback
}

async function loadSharedSpaces() {
  loadingSpaces.value = true
  try {
    sharedSpaces.value = (await listSharedSpaces()) as unknown as SharedSpaceSummary[]
  } catch (e) {
    MessagePlugin.error(errorMessage(e, t('organization.share.loadFailed')))
  } finally {
    loadingSpaces.value = false
  }
}

async function loadShares() {
  if (!props.agentId || !currentTenantId.value || !canManageShares.value) {
    shares.value = []
    return
  }
  loadingShares.value = true
  try {
    shares.value = await listAgentShares(currentTenantId.value, props.agentId)
  } catch (e) {
    MessagePlugin.error(errorMessage(e, t('organization.share.loadFailed')))
  } finally {
    loadingShares.value = false
  }
}

async function handleShare() {
  if (!selectedSpaceId.value) return
  submitting.value = true
  try {
    await shareAgent(currentTenantId.value, props.agentId, {
      shared_space_id: selectedSpaceId.value,
      level: selectedLevel.value,
    })
    MessagePlugin.success(t('organization.share.shareSuccess'))
    selectedSpaceId.value = ''
    selectedLevel.value = 'viewer'
    addPopupVisible.value = false
    await loadShares()
  } catch (e) {
    MessagePlugin.error(errorMessage(e, t('organization.share.shareFailed')))
  } finally {
    submitting.value = false
  }
}

/** 修改已共享空间的级别：后端对同一 (agent, space) 做 upsert，直接重新提交即可。 */
async function handleLevelChange(share: AgentShare, level: AgentShareLevel) {
  if (level === share.level) return
  try {
    await shareAgent(currentTenantId.value, props.agentId, { shared_space_id: share.shared_space_id, level })
    MessagePlugin.success(t('organization.share.levelUpdated'))
    await loadShares()
  } catch (e) {
    MessagePlugin.error(errorMessage(e, t('organization.share.shareFailed')))
    await loadShares()
  }
}

async function handleUnshare(share: AgentShare) {
  try {
    await unshareAgent(currentTenantId.value, props.agentId, share.shared_space_id)
    MessagePlugin.success(t('organization.share.unshareSuccess'))
    await loadShares()
  } catch (e) {
    MessagePlugin.error(errorMessage(e, t('organization.share.unshareFailed')))
  }
}

watch(() => [props.agentId, currentTenantId.value] as const, async ([newId]) => {
  if (newId) await Promise.all([loadSharedSpaces(), loadShares()])
})

onMounted(async () => {
  if (props.agentId) await Promise.all([loadSharedSpaces(), loadShares()])
})

defineExpose({ loadShares })
</script>

<style scoped lang="less">
@import '@/components/share-to-space-panel.less';
</style>

<style lang="less">
@import '@/components/share-to-space-panel.overlay.less';
</style>
