<script setup lang="ts">
import ResourceDirectoryCard from '@nexus-web/core/components/ResourceDirectoryCard.vue'
/** 管理应用组合共享编辑器；不依赖工作台路由或聊天状态。 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import ResourceManagementDirectory from '../../components/ResourceManagementDirectory.vue'
import ResourceDirectoryActions from '../../components/ResourceDirectoryActions.vue'
import ResourceCatalogIcon from '../../components/ResourceCatalogIcon.vue'
import NexusAgentEditorModal from '@nexus-web/core/components/agent-editor/NexusAgentEditorModal.vue'
import AgentAudienceDialog from '@nexus-web/core/components/agent-editor/AgentAudienceDialog.vue'
import { useAgentAdministration } from './useAgentAdministration'
import { useEnterpriseContext } from '../../stores/context'
const { t } = useI18n()
const router = useRouter(), adminContext = useEnterpriseContext()
const { rows, loading, ready, busy, error, search, editor, selected, revision, tenant, canManage, canGrant, filtered, load, open, archive } = useAgentAdministration()
const audienceAgent = ref<(typeof filtered.value)[number] | null>(null), audienceOpen = ref(false)
watch(() => `${tenant.value}:${adminContext.revision}:${canManage.value}`, () => { audienceOpen.value = false; audienceAgent.value = null })
function openModelSettings() {
  if (adminContext.can('models:manage')) void router.push('/models')
  else void MessagePlugin.info(t('adminAgents.modelsPermission'))
}
const cardActions = computed(() => [
  { value: 'edit', label: t('adminAgents.edit'), icon: 'edit' },
  { value: 'audience', label: t('agentAudience.assign'), icon: 'usergroup' },
  { value: 'channels', label: t('connectionUi.channels'), icon: 'link' },
  { value: 'archive', label: t('adminAgents.archive'), icon: 'archive', danger: true },
])
function onCardAction(action: string, row: (typeof rows.value)[number]) {
  switch (action) {
    case 'edit': open(row); break
    case 'audience': audienceAgent.value = row; audienceOpen.value = true; break
    case 'channels': void router.push({ path: '/channels', query: { agent: row.id } }); break
    case 'archive': archive(row); break
  }
}
</script>
<template>
  <ResourceManagementDirectory
    v-model:query="search" :title="t('consoleLayout.agentManagement')" :description="t('adminAgents.description')" :scope-hint="t('adminAgents.scopeHint')"
    resource="agent" :create-label="t('adminAgents.create')" :search-label="t('adminAgents.search')"
    :empty-label="t('adminAgents.empty')" :allowed="canManage" :loading="loading" :ready="ready"
    :disabled="busy || editor || audienceOpen" :error="error" :total="rows.length" :items="filtered"
    @create="open()" @refresh="load">
    <template #toolbar>
      <RouterLink v-if="canGrant" class="grants-link" to="/roles">{{ t('adminAgents.grants') }}<t-icon name="chevron-right" /></RouterLink>
    </template>
    <template #default="{ items }">
      <ResourceDirectoryCard v-for="row in items" :key="row.id" :title="row.name" :description="row.description"
        :empty-description="t('adminAgents.noDescription')" :interactive="row.can_maintain && !busy && !editor" @open="open(row)">
        <template #avatar><ResourceCatalogIcon class="agent-avatar-icon" kind="agent" :size="16" /></template>
        <template #menu>
          <ResourceDirectoryActions v-if="row.can_maintain" :actions="cardActions" :disabled="busy || editor || audienceOpen" @select="onCardAction($event, row)" />
        </template>
        <div class="agent-card-status">
          <t-tag size="small" :theme="row.status === 'published' ? 'success' : 'default'" variant="light">{{ t(`adminAgents.${row.status}`, row.status) }}</t-tag>
          <span>{{ t('adminAgents.version', { version: row.version_counter }) }}</span>
        </div>
      </ResourceDirectoryCard>
    </template>
  </ResourceManagementDirectory>
  <NexusAgentEditorModal v-if="editor" :key="revision" :visible="editor" :tenant-id="tenant" :agent-id="selected" creation-scope="enterprise" @close="editor = false" @saved="load" @open-model-settings="openModelSettings" />
  <AgentAudienceDialog v-if="audienceAgent" v-model:visible="audienceOpen" :tenant-id="tenant" :agent-id="audienceAgent.id" :agent-name="audienceAgent.name" :scope-key="`${tenant}:${audienceAgent.id}:${adminContext.revision}`" :can-manage="canManage && !!audienceAgent.can_maintain" :can-read-members="adminContext.can('members:manage')" :can-read-organization="adminContext.can('org:manage')" admin-api @saved="MessagePlugin.success(t('agentAudience.saved'))" />
</template>

<style scoped>
.grants-link { display: inline-flex; align-items: center; gap: 4px; color: var(--td-brand-color); text-decoration: none; }
.grants-link:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
.agent-avatar-icon { color: var(--td-text-color-secondary); }
.agent-card-status { display: flex; gap: 8px; align-items: center; color: var(--td-text-color-secondary); font-size: var(--app-text-sm); }
</style>
