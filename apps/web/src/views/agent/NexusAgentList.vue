<template>
  <!--
    Nexus agent list (openspec 2026-11-05-weknora-agent-tool-model-settings).
    Header, card grid and card markup follow WeKnora `views/agent/AgentList.vue`; data comes from
    `GET /tenants/{id}/agents`. WeKnora's space filters, favorites, built-in and shared sections are
    omitted: Nexus lists one space's agents, and sharing is managed in shared spaces.
  -->
  <div class="agent-list-container">
    <div class="agent-list-content">
      <div class="header">
        <div class="header-title">
          <div class="title-row">
            <h2>
              <ResourceIcon type="agent" :size="24" />
              {{ $t('agent.title') }}
            </h2>
            <div class="header-actions">
              <t-input v-model="keyword" class="agent-search" size="small" clearable
                :placeholder="$t('nexusAgent.searchPlaceholder')" :aria-label="$t('nexusAgent.searchPlaceholder')">
                <template #prefix-icon><t-icon name="search" size="16px" /></template>
              </t-input>
              <t-tooltip v-if="canCreate" :content="$t('agent.createAgent')" placement="bottom">
                <t-button variant="text" theme="default" size="small" class="header-action-btn" @click="openCreate">
                  <template #icon><t-icon name="add" /></template>
                  {{ $t('agent.createAgent') }}
                </t-button>
              </t-tooltip>
            </div>
          </div>
          <p class="header-subtitle">{{ $t('agent.subtitle') }}</p>
        </div>
      </div>

      <div class="agent-list-main">
        <t-alert v-if="loadError" theme="error" :message="loadError" class="agent-list-alert" />

        <div v-if="loading && agents.length === 0" class="agent-card-wrap">
          <div v-for="n in 6" :key="'skel-' + n" class="agent-card agent-card-skeleton is-skeleton">
            <div class="card-header">
              <div class="card-header-left">
                <t-skeleton animation="gradient"
                  :row-col="[[{ width: '32px', height: '32px', type: 'circle' }, { width: '40%', height: '18px' }]]" />
              </div>
            </div>
            <div class="card-content">
              <t-skeleton animation="gradient" :row-col="[{ width: '100%', height: '14px' }, { width: '70%', height: '14px' }]" />
            </div>
          </div>
        </div>

        <EmptyState v-else-if="!tenantId" icon="usergroup" :title="$t('nexusAgent.noSpace')" />
        <EmptyState v-else-if="!loading && keyword.trim() && filteredAgents.length === 0" icon="search" :title="$t('common.noResult')">
          <t-button variant="outline" @click="keyword = ''">{{ $t('common.clear') }}</t-button>
        </EmptyState>
        <EmptyState v-else-if="!loading && agents.length === 0 && !loadError" icon="control-platform"
          :title="$t('nexusAgent.empty')" :description="$t('nexusAgent.emptyDesc')">
          <t-button v-if="canCreate" theme="primary" @click="openCreate">{{ $t('agent.createAgent') }}</t-button>
        </EmptyState>

        <div v-else class="agent-card-wrap">
          <div v-for="agent in filteredAgents" :key="agent.id" class="agent-card agent-mode-agent" role="link" tabindex="0"
            @click="handleCardClick(agent)" @keydown.enter.self.prevent="handleCardClick(agent)">
            <div class="card-header">
              <div class="card-header-left">
                <ResourceCardAvatar kind="agent" />
                <span class="card-title" :title="agent.name">{{ agent.name }}</span>
              </div>
              <t-popup v-if="canCreate" :visible="openMoreId === agent.id" trigger="click" overlayClassName="card-more-popup"
                destroy-on-close placement="bottom-right" @update:visible="(v: boolean) => { openMoreId = v ? agent.id : null }">
                <button type="button" :aria-label="$t('common.expand')" class="more-wrap"
                  :class="{ 'active-more': openMoreId === agent.id }" aria-haspopup="true" @click.stop>
                  <t-icon name="ellipsis" size="16px" aria-hidden="true" />
                </button>
                <template #content>
                  <div class="popup-menu">
                    <div class="popup-menu-item" @click="startChat(agent)">
                      <t-icon class="menu-icon" name="chat" /><span>{{ $t('nexusAgent.startChat') }}</span>
                    </div>
                    <div class="popup-menu-item" @click="openEdit(agent)">
                      <t-icon class="menu-icon" name="edit" /><span>{{ $t('common.edit') }}</span>
                    </div>
                    <div class="popup-menu-item" @click="handleCopy(agent)">
                      <t-icon class="menu-icon" name="file-copy" /><span>{{ $t('common.copy') }}</span>
                    </div>
                    <div class="popup-menu-item delete" @click="handleDelete(agent)">
                      <t-icon class="menu-icon" name="delete" /><span>{{ $t('common.delete') }}</span>
                    </div>
                  </div>
                </template>
              </t-popup>
            </div>
            <div class="card-content">
              <div class="card-description" :class="{ 'is-empty': !agent.description }"
                :title="agent.description || $t('agent.noDescription')">
                {{ agent.description || $t('agent.noDescription') }}
              </div>
            </div>
            <div class="card-bottom">
              <div class="bottom-left">
                <div class="feature-badges">
                  <t-tooltip :content="$t('agent.mode.agent')" placement="top">
                    <div class="feature-badge mode-agent"><t-icon name="control-platform" size="14px" /></div>
                  </t-tooltip>
                  <t-tooltip v-if="toolCount(agent) > 0" :content="`${$t('agent.editor.toolsConfig')} · ${toolCount(agent)}`" placement="top">
                    <div class="feature-badge mcp"><t-icon name="tools" size="14px" /></div>
                  </t-tooltip>
                </div>
              </div>
              <div class="builtin-badge">
                <span>{{ agent.published_version_id && agent.status === 'published'
                  ? $t('nexusAgent.versionTag', { version: agent.version_counter }) : $t('nexusAgent.draft') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <NexusAgentEditorModal v-if="tenantId" :visible="editorVisible" :tenant-id="tenantId" :agent-id="editingId"
      @close="editorVisible = false" @saved="reload" />
  </div>
</template>

<script setup lang="ts">
/**
 * Agent list on Nexus. Clicking a card opens the editor for managers (WeKnora behaviour) and starts a
 * chat for others. Delete archives the agent (proposal decision 2). Permissions are enforced by the
 * server; the page only hides entry points from roles below contributor.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import EmptyState from '@/components/EmptyState.vue'
import ResourceIcon from '@/components/icons/ResourceIcon.vue'
import ResourceCardAvatar from '@/components/ResourceCardAvatar.vue'
import { useAuthStore } from '@/stores/auth'
import { archiveNexusAgent, copyNexusAgent, listNexusAgents, type NexusAgent } from '@/api/nexus-agents'
import NexusAgentEditorModal from './NexusAgentEditorModal.vue'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const tenantId = computed(() => authStore.effectiveTenantId ? String(authStore.effectiveTenantId) : '')
const canCreate = computed(() => authStore.hasRole('contributor'))
const agents = ref<NexusAgent[]>([])
const loading = ref(false)
const loadError = ref('')
const keyword = ref('')
const openMoreId = ref<string | null>(null)
const editorVisible = ref(false)
const editingId = ref<string | null>(null)

const filteredAgents = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  const sorted = [...agents.value].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  if (!needle) return sorted
  return sorted.filter(agent => agent.name.toLowerCase().includes(needle)
    || (agent.description || '').toLowerCase().includes(needle))
})

function toolCount(agent: NexusAgent): number {
  return (agent.resource_bindings || []).filter(binding => binding.kind === 'tool').length
}

function errorMessage(error: unknown, fallback: string): string {
  const message = error && typeof error === 'object' ? (error as { message?: unknown }).message : undefined
  return typeof message === 'string' && message ? message : fallback
}

async function reload() {
  if (!tenantId.value) return
  loading.value = true
  loadError.value = ''
  try {
    agents.value = await listNexusAgents(tenantId.value)
  } catch (error) {
    loadError.value = errorMessage(error, t('nexusAgent.loadFailed'))
  } finally {
    loading.value = false
  }
}

watch(tenantId, () => { void reload() }, { immediate: true })

function openCreate() {
  editingId.value = null
  editorVisible.value = true
}

function openEdit(agent: NexusAgent) {
  openMoreId.value = null
  editingId.value = agent.id
  editorVisible.value = true
}

function startChat(agent: NexusAgent) {
  openMoreId.value = null
  if (!agent.published_version_id) {
    MessagePlugin.warning(t('nexusAgent.notPublished'))
    return
  }
  void router.push({ path: '/platform/creatChat', query: { agent: agent.published_version_id } })
}

function handleCardClick(agent: NexusAgent) {
  if (canCreate.value) openEdit(agent)
  else startChat(agent)
}

async function handleCopy(agent: NexusAgent) {
  openMoreId.value = null
  try {
    const copied = await copyNexusAgent(tenantId.value, agent.id, `${agent.name} (${t('nexusAgent.copySuffix')})`)
    MessagePlugin.success(t('nexusAgent.copied', { name: copied.name }))
    await reload()
  } catch (error) {
    MessagePlugin.error(errorMessage(error, t('nexusAgent.saveFailed')))
  }
}

function handleDelete(agent: NexusAgent) {
  openMoreId.value = null
  const dialog = DialogPlugin.confirm({
    header: t('nexusAgent.deleteTitle'),
    body: t('nexusAgent.deleteConfirm', { name: agent.name }),
    confirmBtn: { content: t('common.delete'), theme: 'danger' },
    cancelBtn: t('common.cancel'),
    onConfirm: async () => {
      try {
        await archiveNexusAgent(tenantId.value, agent.id)
        MessagePlugin.success(t('nexusAgent.deleted'))
        dialog.destroy()
        await reload()
      } catch (error) {
        MessagePlugin.error(errorMessage(error, t('nexusAgent.saveFailed')))
      }
    },
  })
}
</script>

<style scoped lang="less">
// Copied from WeKnora views/agent/AgentList.vue (header, grid and cards).
@import (reference) '@/components/css/resource-card.less';

.agent-list-container {
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
}

.agent-list-content { .resource-list-content(); }

.agent-list-main { .resource-list-main(); }

.agent-list-alert {
  margin-bottom: 12px;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-right: 28px;

  .header-title {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
    min-width: 0;
  }

  .title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  h2 {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    color: var(--td-text-color-primary);
    font-family: var(--app-font-family);
    font-size: var(--app-text-4xl);
    font-weight: 600;
    line-height: 32px;
  }
}

.header-subtitle {
  margin: 0;
  color: var(--td-text-color-placeholder);
  font-family: var(--app-font-family);
  font-size: var(--app-text-base);
  font-weight: 400;
  line-height: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.agent-search {
  width: 220px;
}

.header-action-btn {
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--td-bg-color-secondarycontainer);
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-sm);
  color: var(--td-text-color-secondary);
  cursor: pointer;
  box-shadow: inset 0 1px 0 color-mix(in srgb, var(--td-bg-color-container) 72%, transparent);
  transition: background var(--app-motion-base), border-color var(--app-motion-base), color var(--app-motion-base);

  &:hover {
    background: var(--td-bg-color-secondarycontainer);
    border-color: var(--td-component-stroke);
    color: var(--td-text-color-primary);
  }

  :deep(.t-icon) {
    color: var(--td-brand-color);
  }
}

.agent-card-wrap {
  .resource-card-grid();
}

.agent-card {
  .resource-card();

  .resource-card-quiet();
}

.builtin-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: var(--app-radius-lg);
  background: var(--td-bg-color-container-hover);
  color: var(--td-text-color-secondary);
  font-family: var(--app-font-family);
  font-size: var(--app-text-xs);
  font-weight: 500;
  flex-shrink: 0;
}

.bottom-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.feature-badge {
  .resource-feature-badge();
}

.resource-list-header();
</style>
