<script setup lang="ts">
/** 管理端部门组织页：可读组织路径、节点维护与当前节点的直接成员归属。 */
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { useOrganizationAdministration } from './useOrganizationAdministration'
const { t } = useI18n()
const state = reactive(useOrganizationAdministration(t))
const columns = computed(() => [{ colKey: 'person', title: t('adminMembers.person'), minWidth: 200 }, { colKey: 'is_primary', title: t('adminOrganization.primary'), width: 120 }, { colKey: 'actions', title: t('adminMembers.operations'), minWidth: 230 }])
const editorTitle = computed(() => t(state.editorMode === 'root' ? 'adminOrganization.createRoot' : state.editorMode === 'edit' ? 'adminOrganization.edit' : 'adminOrganization.createChild'))
const rules = computed(() => ({ name: [{ required: true, message: t('adminOrganization.nameRequired'), type: 'error' }] }))
function refresh() { if (!state.busy && !state.loading) void state.load(state.selectedId) }
</script>
<template>
  <section class="organization-page">
    <header><div><h1>{{ t('adminOrganization.title') }}</h1><p>{{ t('adminOrganization.description') }}</p></div><div class="organization-actions"><t-button variant="outline" :disabled="state.busy" :loading="state.loading" @click="refresh">{{ t('connectionUi.refresh') }}</t-button><t-button v-if="state.canManage && state.treeReady && !state.units.length" :disabled="state.busy || state.loading" @click="state.openCreate(null)">{{ t('adminOrganization.createRoot') }}</t-button></div></header>
    <t-alert v-if="!state.canManage" theme="warning" :message="t('adminOrganization.denied')" />
    <template v-else>
      <t-alert v-if="state.error" theme="error" :message="state.error" />
      <t-alert v-if="state.success" theme="success" :message="state.success" />
      <t-loading :loading="state.loading">
        <t-empty v-if="state.treeReady && !state.units.length" :description="t('adminOrganization.empty')" />
        <div v-else-if="state.treeReady" class="organization-layout">
          <nav class="organization-tree" :aria-label="t('adminOrganization.treeLabel')">
            <button v-for="row in state.rows" :key="row.node.id" type="button" :aria-current="state.selectedId === row.node.id ? 'true' : undefined" :class="{ selected: state.selectedId === row.node.id }" :style="{ paddingLeft: `${12 + Math.min(row.depth, 12) * 12}px` }" :title="row.path" :disabled="state.busy || state.loading" @click="state.selectUnit(row.node.id)"><span>{{ row.node.name }}</span><small>{{ row.node.member_count }}</small><t-tag v-if="row.node.status === 'disabled'" theme="warning" size="small">{{ t('adminOrganization.status.disabled') }}</t-tag></button>
          </nav>
          <section v-if="state.selected" class="organization-detail">
            <header><div><h2>{{ state.selected.name }}</h2><p>{{ state.path(state.selected.id) }}</p></div><div class="organization-actions"><t-tag :theme="state.selected.status === 'active' ? 'success' : 'warning'">{{ t(`adminOrganization.status.${state.selected.status}`) }}</t-tag><t-tag>{{ t(`adminOrganization.source.${state.selected.source}`) }}</t-tag></div></header>
            <t-alert v-if="!state.manual" theme="info" :message="t('adminOrganization.wecomReadOnly')" />
            <div class="organization-actions">
              <t-button variant="outline" :disabled="state.busy || state.selected.status !== 'active'" @click="state.openCreate(state.selected.id)">{{ t('adminOrganization.createChild') }}</t-button>
              <template v-if="state.manual"><t-button variant="outline" :disabled="state.busy" @click="state.openEdit">{{ t('adminOrganization.edit') }}</t-button><t-button variant="outline" :disabled="state.busy" @click="state.toggleStatus">{{ t(state.selected.status === 'active' ? 'adminOrganization.disable' : 'adminOrganization.enable') }}</t-button><t-button theme="danger" variant="outline" :disabled="state.busy || !state.canDelete" @click="state.removeUnit">{{ t('adminOrganization.delete') }}</t-button></template>
            </div>
            <p v-if="state.selected.parent_id === null">{{ t('adminOrganization.rootHint') }}</p>
            <h3>{{ t('adminOrganization.members') }}</h3>
            <t-alert v-if="state.membersError" theme="error" :message="state.membersError"><template #operation><t-button variant="text" :disabled="state.busy" @click="state.selectUnit(state.selected.id)">{{ t('connectionUi.refresh') }}</t-button></template></t-alert>
            <t-table v-if="state.membersReady || state.membersLoading" row-key="user_id" :data="state.members" :columns="columns" :loading="state.membersLoading" :empty="t('adminOrganization.noMembers')">
              <template #person="{ row }">{{ state.memberName(row) }}</template>
              <template #is_primary="{ row }"><t-tag v-if="row.is_primary" theme="primary">{{ t('adminOrganization.primary') }}</t-tag><span v-else>{{ t('adminOrganization.secondary') }}</span></template>
              <template #actions="{ row }"><div v-if="state.manual" class="organization-actions"><t-button variant="text" :disabled="state.busy || row.is_primary || state.selected.status !== 'active'" @click="state.setPrimary(row)">{{ t('adminOrganization.setPrimary') }}</t-button><t-button theme="danger" variant="text" :disabled="state.busy" @click="state.removeMember(row)">{{ t('adminOrganization.removeMember') }}</t-button></div><span v-else>{{ t('adminOrganization.readOnly') }}</span></template>
            </t-table>
            <template v-if="state.manual">
              <t-alert v-if="!state.canReadCandidates" theme="info" :message="t('adminOrganization.candidatePermission')" />
              <t-alert v-else-if="state.candidatesError" theme="warning" :message="t('adminOrganization.candidateFailed')" />
              <t-form v-else :data="state.assignment" layout="vertical" :disabled="state.busy || !state.canAssign" class="assignment-form" @submit="state.assign">
                <t-form-item :label="t('adminOrganization.chooseMember')"><t-select v-model="state.assignment.user_id" :options="state.candidateOptions" filterable /></t-form-item>
                <t-form-item :label="t('adminOrganization.makePrimary')"><t-switch v-model="state.assignment.is_primary" :aria-label="t('adminOrganization.makePrimary')" /></t-form-item>
                <p>{{ t('adminOrganization.primaryHint') }}</p>
                <t-button type="submit" theme="primary" :disabled="!state.canAssign || !state.assignment.user_id" :loading="state.busy">{{ t('adminOrganization.assign') }}</t-button>
              </t-form>
            </template>
          </section>
        </div>
      </t-loading>
      <p>{{ t('adminOrganization.deleteHint') }}</p>
    </template>
    <t-dialog :visible="state.editorOpen" :header="editorTitle" :footer="false" :close-btn="!state.busy" :close-on-overlay-click="!state.busy" :close-on-esc-keydown="!state.busy" @close="state.closeEditor">
      <t-alert v-if="state.error" theme="error" :message="state.error" />
      <t-form :data="state.form" :rules="rules" layout="vertical" :disabled="state.busy" @submit="state.save">
        <t-form-item name="name" :label="t('adminOrganization.name')"><t-input v-model="state.form.name" :maxlength="160" /></t-form-item>
        <t-form-item v-if="state.editorMode === 'create' || (state.editorMode === 'edit' && state.selected?.parent_id !== null)" :label="t('adminOrganization.parent')"><t-select v-model="state.form.parent_id" :options="state.parentOptions" filterable /></t-form-item>
        <p v-else>{{ t('adminOrganization.rootHint') }}</p>
        <div class="organization-actions"><t-button type="submit" theme="primary" :loading="state.busy" :disabled="!state.form.name.trim()">{{ t('common.save') }}</t-button><t-button variant="outline" :disabled="state.busy" @click="state.closeEditor">{{ t('common.cancel') }}</t-button></div>
      </t-form>
    </t-dialog>
  </section>
</template>
<style scoped>
.organization-page { display: grid; gap: 20px; }
.organization-page header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; flex-wrap: wrap; }
h1 { margin: 0 0 12px; font-size: 24px; } h2,h3 { margin: 0 0 12px; }
p { color: var(--td-text-color-secondary); line-height: 1.6; overflow-wrap: anywhere; }
.organization-layout { display: grid; grid-template-columns: minmax(230px, 300px) minmax(0, 1fr); gap: 24px; }
.organization-tree { border: 1px solid var(--td-component-border); background: var(--td-bg-color-container); border-radius: var(--td-radius-default); padding: 8px; align-self: start; }
.organization-tree button { width: 100%; padding: 12px; display: flex; align-items: center; gap: 8px; border: 0; background: transparent; color: var(--td-text-color-primary); text-align: left; cursor: pointer; border-radius: var(--td-radius-default); }
.organization-tree button span { flex: 1; overflow-wrap: anywhere; min-width: 0; }
.organization-tree button.selected { color: var(--td-brand-color); background: var(--td-brand-color-light); }
.organization-tree button:focus-visible { outline: 2px solid var(--td-brand-color); outline-offset: 2px; }
.organization-tree button:disabled { cursor: wait; }
.organization-detail { min-width: 0; display: grid; align-content: start; gap: 20px; }
.organization-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.assignment-form { padding: 24px; border: 1px solid var(--td-component-border); border-radius: var(--td-radius-default); background: var(--td-bg-color-container); }
@media(max-width: 1000px) { .organization-layout { grid-template-columns: 1fr; } }
</style>
