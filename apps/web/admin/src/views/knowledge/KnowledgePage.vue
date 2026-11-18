<script setup lang="ts">
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import ResourceDirectoryCard from '@nexus-web/core/components/ResourceDirectoryCard.vue'
/** 企业库目录、完整设置、读取受众与知识库管理员。 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import KnowledgeBaseEditorModal from '@nexus-web/core/components/knowledge-editor/KnowledgeBaseEditorModal.vue'
import KnowledgeAudienceDialog from './KnowledgeAudienceDialog.vue'
import type { EnterpriseKnowledgeBase } from '@nexus-web/core/api/enterprise-knowledge'
import { useI18n } from 'vue-i18n'
import { useKnowledgeAdministration } from './useKnowledgeAdministration'
const { t } = useI18n()
const router = useRouter()
const { editor, editingId, editorKey, tenant, openEditor, openSettings, audienceTarget, closeAudience, audienceSaved, openAudience, loading, ready, error, search, selected, maintainers, maintainersReady, membersReady, panelLoading, busy, panelError, membersError, success, selectedMember, canManage, canReadMembers, canReadOrganization, filtered, memberOptions, maintainerName, canAdd, editable, load, inspect, closePanel, add, remove, deleteBase } = useKnowledgeAdministration()
const panelRoot = ref<HTMLElement | null>(null)
async function openMaintainers(row: EnterpriseKnowledgeBase) {
  await inspect(row)
  if (selected.value?.id === row.id) panelRoot.value?.focus()
}
</script>
<template>
  <section class="knowledge-page">
    <header class="section-header"><div><h2><t-icon name="folder" size="24px" />{{ t('consoleLayout.knowledgeManagement') }}</h2><p>{{ t('adminKnowledge.description') }}</p></div><div class="actions"><t-button v-if="canManage" theme="primary" :disabled="!ready || busy || editor" @click="openEditor()"><template #icon><t-icon name="add" /></template>{{ t('adminKnowledge.create') }}</t-button><t-button variant="outline" :loading="loading" :disabled="busy || editor" @click="load">{{ t('connectionUi.refresh') }}</t-button></div></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminKnowledge.scopeHint')" />
      <div class="toolbar"><t-input v-model="search" clearable :aria-label="t('adminKnowledge.search')" :placeholder="t('adminKnowledge.search')" /></div>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading">
        <div v-if="ready && filtered.length" class="kb-grid">
          <ResourceDirectoryCard v-for="row in filtered" :key="row.id" :title="row.name" :description="row.description" :interactive="row.can_manage && !busy && !editor" @open="router.push(`/knowledge/${encodeURIComponent(row.id)}/content`)">
            <template #actions><t-dropdown :options="[{ content: t('adminKnowledge.edit'), value: 'edit' }, { content: t('adminKnowledge.audienceManage'), value: 'audience' }, { content: t('adminKnowledge.maintainers'), value: 'maintainers' }, { content: t('adminKnowledge.deleteBase.action'), value: 'delete' }]" :disabled="busy || editor || !!audienceTarget || !row.can_manage" @click="(option: { value?: string | number }) => { if (option.value === 'edit') openEditor(row); if (option.value === 'audience') openAudience(row); if (option.value === 'maintainers') openMaintainers(row); if (option.value === 'delete') deleteBase(row) }"><t-button variant="text" shape="square" :aria-label="t('common.expand')"><t-icon name="ellipsis" /></t-button></t-dropdown></template>
            <span>{{ t('adminKnowledge.documents', { count: row.knowledge_count }) }}</span><t-tag variant="light">{{ t(`adminKnowledge.types.${row.type}`) }}</t-tag><t-button variant="text" :disabled="!row.can_manage" @click="router.push(`/knowledge/${encodeURIComponent(row.id)}/content`)">{{ t('adminKnowledge.content.open') }}</t-button>
          </ResourceDirectoryCard>
        </div>
        <div v-else-if="ready" class="empty"><t-icon :name="search.trim() ? 'search' : 'folder'" size="40px" /><p>{{ t(search.trim() ? 'adminKnowledge.noMatch' : 'adminKnowledge.empty') }}</p></div>
      </t-loading>
      <SettingDrawer :visible="!!selected" :title="t('adminKnowledge.maintainers')" hide-footer @update:visible="(value: boolean) => { if (!value && !busy) closePanel() }">
      <section v-if="selected" id="knowledge-maintainer-panel" ref="panelRoot" tabindex="-1" class="maintainer-panel" :aria-label="t('adminKnowledge.maintainers')">
        <header class="section-header"><div><h3>{{ selected.name }} · {{ t('adminKnowledge.maintainers') }}</h3><p>{{ t('adminKnowledge.maintainerHint') }}</p></div><div class="actions"><t-button variant="outline" :disabled="busy || panelLoading" @click="inspect(selected)">{{ t('connectionUi.refresh') }}</t-button><t-button variant="text" :disabled="busy" @click="closePanel">{{ t('common.close') }}</t-button></div></header>
        <t-alert v-if="success" theme="success" :message="success" />
        <t-alert v-if="panelError" theme="error" :message="panelError" />
        <t-loading :loading="panelLoading">
          <div v-if="maintainersReady" class="data-table-shell maintainer-table"><table><thead><tr><th>{{ t('adminKnowledge.member') }}</th><th>{{ t('adminKnowledge.grantedAt') }}</th><th>{{ t('adminKnowledge.actions') }}</th></tr></thead><tbody><tr v-for="row in maintainers" :key="row.user_id"><td>{{ maintainerName(row) }}<span v-if="row.display_name && row.email" class="email">{{ row.email }}</span></td><td>{{ row.granted_at }}</td><td><t-button variant="text" theme="danger" :disabled="!editable" @click="remove(row)">{{ t('adminKnowledge.remove') }}</t-button></td></tr><tr v-if="!maintainers.length"><td colspan="3">{{ t('adminKnowledge.noMaintainers') }}</td></tr></tbody></table></div>
          <t-alert v-if="!canReadMembers" theme="info" :message="t('adminKnowledge.membersDenied')" />
          <t-alert v-else-if="membersError" theme="error" :message="membersError" />
          <div v-else-if="membersReady" class="add-row"><label>{{ t('adminKnowledge.member') }}<t-select v-model="selectedMember" filterable clearable :disabled="!editable" :options="memberOptions" :placeholder="t('adminKnowledge.chooseMember')" :aria-label="t('adminKnowledge.chooseMember')" /></label><t-button theme="primary" :disabled="!canAdd" :loading="busy" @click="add">{{ t('adminKnowledge.add') }}</t-button><p v-if="maintainersReady && !memberOptions.length">{{ t('adminKnowledge.noCandidates') }}</p></div>
        </t-loading>
      </section>
      </SettingDrawer>
      <KnowledgeBaseEditorModal v-if="editor" :key="editorKey" :visible="editor" :mode="editingId ? 'edit' : 'create'" :kb-id="editingId" :tenant-id="tenant" creation-scope="enterprise" @update:visible="editor = $event" @success="load" @open-settings="openSettings" />
      <KnowledgeAudienceDialog v-if="audienceTarget" :key="`${tenant}:${editorKey}:${audienceTarget.id}`" :visible="true" :tenant-id="tenant" :scope-key="editorKey" :knowledge-base="audienceTarget" :can-read-members="canReadMembers" :can-read-organization="canReadOrganization" @update:visible="(value: boolean) => !value && closeAudience()" @saved="audienceSaved" />
    </template>
  </section>
</template>
<style scoped>
.knowledge-page { width: 100%; min-width: 0; }
.toolbar { margin: 20px 0; }
.toolbar :deep(.t-input__wrap) { width: 320px; max-width: 100%; }
.kb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); gap: 20px; padding: 4px 0 20px; }
.kb-card { min-width: 0; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.kb-card.selected { border-color: var(--td-brand-color); }
.kb-card header, .actions, .metadata { display: flex; align-items: center; gap: 12px; }
h3 { margin: 0; font-size: var(--app-text-lg); overflow-wrap: anywhere; }
.kb-card h3 { flex: 1; min-width: 0; }
.kb-card header > :deep(.t-icon) { flex-shrink: 0; color: var(--td-brand-color); }
.kb-card p { color: var(--td-text-color-secondary); line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; min-height: 52px; }
.kb-card footer { display: flex; justify-content: space-between; flex-wrap: wrap; align-items: center; gap: 8px; border-top: 1px solid var(--td-component-stroke); padding-top: 12px; }
.metadata, .planned { color: var(--td-text-color-secondary); font-size: var(--app-text-md); }
.empty { padding: 60px 20px; text-align: center; color: var(--td-text-color-secondary); }
.maintainer-panel { margin: 0; border: 0; padding: 0; }
.maintainer-panel .section-header { margin-bottom: 20px; }
.maintainer-table { max-width: 100%; overflow-x: auto; margin: 16px 0; }
table { border-collapse: collapse; width: 100%; min-width: 500px; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
.email { display: block; color: var(--td-text-color-secondary); margin-top: 4px; }
.add-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px; margin-top: 20px; }
.add-row label { display: grid; gap: 8px; width: 320px; max-width: 100%; }
.add-row p { color: var(--td-text-color-secondary); }
.planned { margin: 24px 0; line-height: 1.6; }
@media (max-width: 600px) { .maintainer-panel { margin: 0; border: 0; padding: 16px; } .actions { flex-wrap: wrap; } }
</style>

<style scoped>
.section-header h2 { display: flex; align-items: center; gap: 8px; font-size: var(--app-text-4xl); line-height: 32px; font-weight: 600; }
</style>
