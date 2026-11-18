<script setup lang="ts">
/** 企业组织维护仅处理组织节点，成员及组织归属统一在用户管理维护。 */
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import OrganizationTree from '../../components/OrganizationTree.vue'
import EditorDialog from '@nexus-web/core/components/settings/EditorDialog.vue'
import { useOrganizationAdministration } from './useOrganizationAdministration'
const { t } = useI18n(), state = reactive(useOrganizationAdministration(t, { includeMembers: false }))
const search = ref('')
const children = computed(() => state.units.filter(row => row.parent_id === state.selectedId && row.name.toLowerCase().includes(search.value.trim().toLowerCase())))
const edited = computed(() => state.units.find(row => row.id === state.editingId))
const editorTitle = computed(() => t(state.editorMode === 'root' ? 'adminOrganization.createRoot' : state.editorMode === 'edit' ? 'adminOrganization.edit' : 'adminOrganization.createChild'))
const columns = computed(() => [{ colKey: 'name', title: t('adminOrganization.name'), minWidth: 180 }, { colKey: 'source', title: t('enterpriseLayout.source'), width: 130 }, { colKey: 'status', title: t('adminMembers.status'), width: 100 }, { colKey: 'actions', title: t('adminMembers.operations'), minWidth: 230 }])
const rules = computed(() => ({ name: [{ required: true, message: t('adminOrganization.nameRequired'), type: 'error' }] }))
function refresh() { if (!state.busy) void state.load(state.selectedId) }
</script>
<template>
  <section class="organization-page">
    <header class="section-header"><div><h2>{{ t('enterpriseLayout.enterpriseOrganization') }}</h2><p>{{ t('enterpriseLayout.organizationDescription') }}</p></div></header>
    <t-alert v-if="!state.canManage" theme="warning" :message="t('adminOrganization.denied')" />
    <template v-else>
      <t-alert v-if="state.error" theme="error" :message="state.error" />
      <t-alert v-if="state.success" theme="success" :message="state.success" />
      <div class="organization-layout">
        <OrganizationTree :nodes="state.units" :selected-id="state.selectedId" :disabled="state.busy || state.loading" @select="state.selectUnit" />
        <section class="organization-content">
          <div class="organization-toolbar"><t-input v-model="search" clearable :placeholder="t('enterpriseLayout.searchOrganizations')" :aria-label="t('enterpriseLayout.searchOrganizations')"><template #prefix-icon><t-icon name="search" /></template></t-input><div class="organization-actions"><t-button variant="outline" :loading="state.loading" :disabled="state.busy" @click="refresh">{{ t('connectionUi.refresh') }}</t-button><template v-if="state.selected && !state.selected.sync_managed">
            <t-button variant="outline" :disabled="state.busy" @click="state.openEdit()">{{ t('enterpriseLayout.editCurrent') }}</t-button>
            <t-button v-if="state.selected.parent_id === null" variant="outline" :disabled="state.busy" @click="state.toggleStatus()">{{ t(state.selected.status === 'active' ? 'adminOrganization.disable' : 'adminOrganization.enable') }}</t-button>
          </template><t-button theme="primary" :disabled="state.busy || !state.treeReady || state.loading || !!state.selected && state.selected.status !== 'active'" @click="state.openCreate(state.selected?.id || null)"><t-icon name="add" />{{ t('enterpriseLayout.addOrganization') }}</t-button></div></div>
          <p v-if="state.selected" class="organization-path">{{ state.path(state.selected.id) }}</p>
          <t-alert v-if="state.selected?.sync_managed" theme="info" :message="t('adminOrganization.wecomReadOnly')" />
          <div class="data-table-shell"><t-table row-key="id" :data="children" :columns="columns" :loading="state.loading" :empty="t('enterpriseLayout.noChildOrganizations')"><template #name="{ row }"><t-button variant="text" @click="state.selectUnit(row.id)"><t-icon name="folder" />{{ row.name }}</t-button></template><template #source="{ row }">{{ t(`adminOrganization.source.${row.source}`) }}</template><template #status="{ row }"><t-tag :theme="row.status === 'active' ? 'success' : 'warning'">{{ t(`adminOrganization.status.${row.status}`) }}</t-tag></template><template #actions="{ row }"><div v-if="!row.sync_managed" class="organization-actions"><t-button variant="text" :disabled="state.busy" @click="state.openEdit(row.id)">{{ t('common.edit') }}</t-button><t-button variant="text" :disabled="state.busy" @click="state.toggleStatus(row.id)">{{ t(row.status === 'active' ? 'adminOrganization.disable' : 'adminOrganization.enable') }}</t-button><t-button variant="text" theme="danger" :disabled="state.busy || !state.canDeleteUnit(row)" @click="state.removeUnit(row.id)">{{ t('common.delete') }}</t-button></div><span v-else>{{ t('adminOrganization.wecomReadOnly') }}</span></template></t-table></div>
          <p>{{ t('adminOrganization.deleteHint') }}</p>
        </section>
      </div>
    </template>
    <EditorDialog :visible="state.editorOpen" :header="editorTitle" :footer="false" :close-btn="!state.busy" :close-on-overlay-click="!state.busy" @close="state.closeEditor"><t-alert v-if="state.error" theme="error" :message="state.error" /><t-form :data="state.form" :rules="rules" layout="vertical" :disabled="state.busy" @submit="state.save"><t-form-item name="name" :label="t('adminOrganization.name')"><t-input v-model="state.form.name" :maxlength="160" /></t-form-item><t-form-item v-if="state.editorMode === 'create' || state.editorMode === 'edit' && edited?.parent_id !== null" :label="t('adminOrganization.parent')"><t-select v-model="state.form.parent_id" :options="state.parentOptions" filterable /></t-form-item><p v-else>{{ t('adminOrganization.rootHint') }}</p><div class="organization-actions"><t-button type="submit" theme="primary" :loading="state.busy" :disabled="!state.form.name.trim()">{{ t('common.save') }}</t-button><t-button variant="outline" :disabled="state.busy" @click="state.closeEditor">{{ t('common.cancel') }}</t-button></div></t-form></EditorDialog>
  </section>
</template>
<style scoped>
.organization-page { width: 100%; min-width: 0; }
.organization-layout { display: grid; grid-template-columns: 240px minmax(0,1fr); border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); overflow: hidden; min-height: 520px; }
.organization-content { min-width: 0; padding: 20px; } .organization-toolbar, .organization-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.organization-toolbar { justify-content: space-between; margin-bottom: 20px; gap: 16px; } .organization-toolbar :deep(.t-input__wrap) { width: 240px; max-width: 100%; }
p { color: var(--td-text-color-secondary); line-height: 1.6; overflow-wrap: anywhere; } .organization-path { margin: 0 0 16px; }
@media(max-width:720px) { .organization-layout { grid-template-columns: minmax(0,1fr); } .organization-content { padding: 16px; } }
</style>
