<script setup lang="ts">
import SettingDrawer from '@nexus-web/core/components/settings/SettingDrawer.vue'
import ResourceDirectoryCard from '@nexus-web/core/components/ResourceDirectoryCard.vue'
/** 企业库目录、完整设置、读取受众与知识库管理员。 */
import { computed, ref } from 'vue'
import ResourceManagementDirectory from '../../components/ResourceManagementDirectory.vue'
import ResourceDirectoryActions from '../../components/ResourceDirectoryActions.vue'
import { useRouter } from 'vue-router'
import KnowledgeBaseEditorModal from '@nexus-web/core/components/knowledge-editor/KnowledgeBaseEditorModal.vue'
import KnowledgeAudienceDialog from './KnowledgeAudienceDialog.vue'
import type { EnterpriseKnowledgeBase } from '@nexus-web/core/api/enterprise-knowledge'
import { useI18n } from 'vue-i18n'
import { useKnowledgeAdministration } from './useKnowledgeAdministration'
const { t } = useI18n()
const router = useRouter()
const { rows, editor, editingId, editorKey, tenant, openEditor, openSettings, audienceTarget, closeAudience, audienceSaved, openAudience, loading, ready, error, search, selected, maintainers, maintainersReady, membersReady, panelLoading, busy, panelError, membersError, success, selectedMember, canManage, canReadMembers, canReadOrganization, filtered, memberOptions, maintainerName, canAdd, editable, load, inspect, closePanel, add, remove, deleteBase } = useKnowledgeAdministration()
const panelRoot = ref<HTMLElement | null>(null)
async function openMaintainers(row: EnterpriseKnowledgeBase) {
  await inspect(row)
  if (selected.value?.id === row.id) panelRoot.value?.focus()
}
const typeIcons = { document: 'folder', faq: 'chat-bubble-help', wiki: 'book-open' }
const cardActions = computed(() => [
  { value: 'edit', label: t('adminKnowledge.edit'), icon: 'setting' },
  { value: 'audience', label: t('adminKnowledge.audienceManage'), icon: 'usergroup' },
  { value: 'maintainers', label: t('adminKnowledge.maintainers'), icon: 'user-safety' },
  { value: 'delete', label: t('adminKnowledge.deleteBase.action'), icon: 'delete', danger: true },
])
function openContent(row: EnterpriseKnowledgeBase) {
  void router.push(`/knowledge/${encodeURIComponent(row.id)}/content`)
}
function onCardAction(action: string, row: EnterpriseKnowledgeBase) {
  switch (action) {
    case 'edit': openEditor(row); break
    case 'audience': openAudience(row); break
    case 'maintainers': void openMaintainers(row); break
    case 'delete': deleteBase(row); break
  }
}
</script>
<template>
  <ResourceManagementDirectory
    v-model:query="search" :title="t('consoleLayout.knowledgeManagement')" :description="t('adminKnowledge.description')" :scope-hint="t('adminKnowledge.scopeHint')"
    resource="knowledge" :create-label="t('adminKnowledge.create')" :search-label="t('adminKnowledge.search')"
    :empty-label="t('adminKnowledge.empty')" :allowed="canManage" :loading="loading" :ready="ready"
    :disabled="busy || editor || !!audienceTarget" :error="error" :total="rows.length" :items="filtered"
    @create="openEditor()" @refresh="load">
    <template #default="{ items }">
      <ResourceDirectoryCard v-for="row in items" :key="row.id" :title="row.name" :description="row.description"
        :empty-description="t('adminKnowledge.noDescription')" :interactive="row.can_manage && !busy && !editor" @open="openContent(row)">
        <template #avatar>
          <span class="knowledge-avatar" :class="row.type"><t-icon :name="typeIcons[row.type]" size="16px" aria-hidden="true" /></span>
        </template>
        <template #menu>
          <ResourceDirectoryActions v-if="row.can_manage" :actions="cardActions" :disabled="busy || editor || !!audienceTarget" @select="onCardAction($event, row)" />
        </template>
        <span class="knowledge-count" :title="t('adminKnowledge.types.' + row.type)">
          <t-icon :name="row.type === 'document' ? 'file' : typeIcons[row.type]" size="14px" aria-hidden="true" />
          {{ row.knowledge_count }}
        </span>
        <span class="knowledge-type">{{ t('adminKnowledge.types.' + row.type) }}</span>
      </ResourceDirectoryCard>
    </template>
  </ResourceManagementDirectory>
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
<style scoped>
.knowledge-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 28px;
  height: 28px;
  border-radius: var(--app-radius-md);
  color: var(--td-brand-color-active);
  background: linear-gradient(135deg, color-mix(in srgb, var(--td-brand-color) 15%, transparent), color-mix(in srgb, var(--td-brand-color) 8%, transparent));
}
.knowledge-avatar.faq { color: var(--td-info-color, #0052d9); background: color-mix(in srgb, var(--td-info-color, #0052d9) 12%, transparent); }
.knowledge-count, .knowledge-type { color: var(--td-text-color-secondary); font-size: var(--app-text-sm); }
.knowledge-count { display: inline-flex; align-items: center; gap: 4px; font-variant-numeric: tabular-nums; }
.actions { display: flex; align-items: center; gap: 12px; }
h3 { margin: 0; font-size: var(--app-text-lg); overflow-wrap: anywhere; }
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
@media (max-width: 600px) { .maintainer-panel { margin: 0; border: 0; padding: 16px; } .actions { flex-wrap: wrap; } }
</style>
