<script setup lang="ts">
/** 管理应用组合共享编辑器；不依赖工作台路由或聊天状态。 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import AgentAvatar from '@nexus-web/core/components/AgentAvatar.vue'
import NexusAgentEditorModal from '@nexus-web/core/components/agent-editor/NexusAgentEditorModal.vue'
import AgentAudienceDialog from '@nexus-web/core/components/agent-editor/AgentAudienceDialog.vue'
import { useAgentAdministration } from './useAgentAdministration'
import { useAdminContext } from '../../stores/context'
const { t } = useI18n()
const router = useRouter(), adminContext = useAdminContext()
const { loading, ready, busy, error, search, editor, selected, revision, tenant, canManage, canGrant, filtered, load, open, archive } = useAgentAdministration()
const audienceAgent = ref<(typeof filtered.value)[number] | null>(null), audienceOpen = ref(false)
watch(() => `${tenant.value}:${adminContext.revision}:${canManage.value}`, () => { audienceOpen.value = false; audienceAgent.value = null })
function openModelSettings() {
  if (adminContext.can('models:manage')) void router.push('/models')
  else void MessagePlugin.info(t('adminAgents.modelsPermission'))
}
</script>
<template>
  <section class="agents-page">
    <header class="section-header"><div><h2>{{ t('adminAgents.title') }}</h2><p>{{ t('adminAgents.description') }}</p></div><div class="actions"><t-button variant="outline" :loading="loading" :disabled="busy || editor" @click="load">{{ t('connectionUi.refresh') }}</t-button><t-button v-if="canManage" theme="primary" :disabled="!ready || busy || editor" @click="open()"><template #icon><t-icon name="add" /></template>{{ t('adminAgents.create') }}</t-button></div></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminAgents.scopeHint')" />
      <div class="toolbar"><t-input v-model="search" clearable :aria-label="t('adminAgents.search')" :placeholder="t('adminAgents.search')" /><RouterLink v-if="canGrant" to="/roles">{{ t('adminAgents.grants') }}<t-icon name="chevron-right" /></RouterLink></div>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading">
        <div v-if="ready && filtered.length" class="agent-grid">
          <article v-for="row in filtered" :key="row.id" class="agent-card">
            <header><AgentAvatar :name="row.name" size="medium" /><h3>{{ row.name }}</h3><t-tag :theme="row.status === 'published' ? 'success' : 'default'" variant="light">{{ t(`adminAgents.${row.status}`) }}</t-tag></header>
            <p>{{ row.description || t('adminAgents.noDescription') }}</p>
          <footer><span>{{ t('adminAgents.version', { version: row.version_counter }) }}</span><div class="actions"><t-button variant="text" :disabled="busy || editor || audienceOpen || !row.can_maintain" @click="open(row)">{{ t('adminAgents.edit') }}</t-button><t-button variant="text" :disabled="busy || editor || audienceOpen || !row.can_maintain" @click="audienceAgent = row; audienceOpen = true">{{ t('agentAudience.assign') }}</t-button><t-button variant="text" theme="danger" :disabled="busy || editor || audienceOpen || !row.can_maintain" @click="archive(row)">{{ t('adminAgents.archive') }}</t-button></div></footer>
          </article>
        </div>
        <div v-else-if="ready" class="empty"><t-icon :name="search.trim() ? 'search' : 'app'" size="40px" /><p>{{ t(search.trim() ? 'adminAgents.noMatch' : 'adminAgents.empty') }}</p></div>
      </t-loading>
      <NexusAgentEditorModal v-if="editor" :key="revision" :visible="editor" :tenant-id="tenant" :agent-id="selected" creation-scope="enterprise" @close="editor = false" @saved="load" @open-model-settings="openModelSettings" />
      <AgentAudienceDialog v-if="audienceAgent" v-model:visible="audienceOpen" :tenant-id="tenant" :agent-id="audienceAgent.id" :agent-name="audienceAgent.name" :scope-key="`${tenant}:${audienceAgent.id}:${adminContext.revision}`" :can-manage="canManage && !!audienceAgent.can_maintain" :can-read-members="adminContext.can('members:manage')" :can-read-organization="adminContext.can('org:manage')" @saved="MessagePlugin.success(t('agentAudience.saved'))" />
    </template>
  </section>
</template>
<style scoped>
.agents-page { width: 100%; min-width: 0; }
.actions, .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.toolbar { justify-content: space-between; margin: 20px 0; gap: 16px; }
.toolbar :deep(.t-input__wrap) { width: 320px; max-width: 100%; }
a { display: inline-flex; align-items: center; color: var(--td-brand-color); text-decoration: none; min-height: 40px; }
a:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
.agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); gap: 20px; padding: 4px 0 20px; }
.agent-card { min-width: 0; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); padding: 20px; background: var(--td-bg-color-container); }
.agent-card header { display: flex; align-items: center; gap: 12px; }
h3 { flex: 1; min-width: 0; margin: 0; font-size: var(--app-text-lg); overflow-wrap: anywhere; }
.agent-card p { color: var(--td-text-color-secondary); line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; min-height: 52px; }
.agent-card footer { display: flex; justify-content: space-between; flex-wrap: wrap; align-items: center; gap: 8px; border-top: 1px solid var(--td-component-stroke); padding-top: 12px; }
.agent-card footer > span { color: var(--td-text-color-secondary); }
.empty { padding: 60px 20px; text-align: center; color: var(--td-text-color-secondary); }
</style>
