<script setup lang="ts">
/** 企业角色页面仅组合授权状态与表单，不直接调用接口。 */
import { useI18n } from 'vue-i18n'
import { useRoleAdministration } from './useRoleAdministration'
const { t } = useI18n()
const { catalog, actor, ready, membersReady, loading, busy, error, membersError, success, search, editor, selected, form, selectedMember, selectedRole, canManage, canManageMembers, filteredRoles, valid, assignableRoles, memberChoices, assignmentRows, canAssign, memberName, permissionLabel, closeEditor, load, openEditor, save, assign, revoke } = useRoleAdministration()
const groups = ['menus', 'apis'] as const
</script>
<template>
  <section class="roles-page">
    <header class="section-header"><div><h2>{{ t('adminRoles.title') }}</h2><p>{{ t('adminRoles.description') }}</p></div><div class="toolbar"><t-button class="settings-list-button" variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button><t-button theme="primary" :disabled="!ready || busy || loading" @click="openEditor()">{{ t('adminRoles.create') }}</t-button></div></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <t-alert v-if="error" theme="error" :message="error" />
    <t-alert v-if="success" theme="success" :message="success" />
    <t-loading :loading="loading">
      <template v-if="ready">
        <t-input v-model="search" class="role-search" :aria-label="t('adminRoles.search')" :placeholder="t('adminRoles.search')" clearable />
        <div class="data-table-shell role-table"><table><thead><tr><th>{{ t('adminRoles.name') }}</th><th>{{ t('adminRoles.type') }}</th><th>{{ t('adminRoles.permissions') }}</th><th>{{ t('adminRoles.operation') }}</th></tr></thead><tbody><tr v-for="row in filteredRoles" :key="row.id"><td>{{ row.name }}</td><td>{{ t(row.builtin ? 'adminRoles.builtin' : 'adminRoles.custom') }}</td><td><span v-for="kind in groups" :key="kind" class="grant-summary">{{ t(`adminRoles.${kind}Title`) }} {{ row[kind].length }}</span></td><td><t-button variant="text" :disabled="busy || loading" @click="openEditor(row)">{{ t(row.builtin ? 'adminRoles.view' : 'common.edit') }}</t-button></td></tr><tr v-if="!filteredRoles.length"><td colspan="4">{{ t('adminRoles.empty') }}</td></tr></tbody></table></div>
        <h3>{{ t('adminRoles.assignments') }}</h3>
        <t-alert v-if="!canManageMembers" theme="info" :message="t('adminRoles.membersDenied')" />
        <t-alert v-else-if="membersError" theme="error" :message="membersError" />
        <template v-else-if="membersReady">
          <div class="assignment-form"><t-select v-model="selectedMember" :options="memberChoices" :aria-label="t('adminRoles.member')" :placeholder="t('adminRoles.member')" filterable :disabled="busy" /><t-select v-model="selectedRole" :options="assignableRoles.map(row => ({ value: row.id, label: row.name }))" :aria-label="t('adminRoles.role')" :placeholder="t('adminRoles.role')" filterable :disabled="busy" /><t-button theme="primary" :disabled="!canAssign || loading" @click="assign">{{ t('adminRoles.assign') }}</t-button></div>
          <p class="hint">{{ t('adminRoles.assignmentHint') }}</p>
          <div class="data-table-shell role-table"><table><thead><tr><th>{{ t('adminRoles.member') }}</th><th>{{ t('adminRoles.role') }}</th><th>{{ t('adminRoles.operation') }}</th></tr></thead><tbody><tr v-for="row in assignmentRows" :key="`${row.user_id}:${row.role_id}`"><td>{{ row.member ? memberName(row.member) : '' }}</td><td>{{ row.role?.name }}</td><td><t-button variant="text" theme="danger" :disabled="busy || loading" @click="revoke(row.user_id, row.role_id)">{{ t('adminRoles.revoke') }}</t-button></td></tr><tr v-if="!assignmentRows.length"><td colspan="3">{{ t('adminRoles.noAssignments') }}</td></tr></tbody></table></div>
        </template>
      </template>
    </t-loading>
    <t-dialog :visible="editor" :header="t(selected?.builtin ? 'adminRoles.view' : selected ? 'adminRoles.edit' : 'adminRoles.create')" width="680px" :footer="false" :close-btn="!busy" :close-on-overlay-click="!busy" :close-on-esc-keydown="!busy" @close="closeEditor">
      <t-form :data="form" layout="vertical" @submit="save">
        <t-form-item :label="t('adminRoles.name')" :help="t('adminRoles.nameHint')"><t-input v-model="form.name" :aria-label="t('adminRoles.name')" :maxlength="64" :disabled="!!selected || busy" /></t-form-item>
        <t-alert v-if="selected?.builtin" theme="info" :message="t('adminRoles.builtinHint')" />
        <p class="hint">{{ t('adminRoles.limitHint') }}</p>
        <fieldset v-for="kind in groups" :key="kind" :disabled="busy || !!selected?.builtin"><legend>{{ t(`adminRoles.${kind}Title`) }}</legend><t-checkbox-group v-model="form[kind]" class="permission-options"><t-checkbox v-for="key in [...new Set([...(catalog?.[kind] || []), ...form[kind]])]" :key="key" :value="key" :disabled="busy || !!selected?.builtin || (!actor?.[kind].includes(key) && !form[kind].includes(key))">{{ permissionLabel(kind, key) }}</t-checkbox></t-checkbox-group></fieldset>
        <t-alert v-if="error" theme="error" :message="error" />
        <div class="editor-actions"><t-button v-if="!selected?.builtin" type="submit" theme="primary" :loading="busy" :disabled="!valid || loading">{{ t('common.save') }}</t-button><t-button variant="outline" :disabled="busy" @click="closeEditor">{{ t('common.cancel') }}</t-button></div>
      </t-form>
    </t-dialog>
  </section>
</template>
<style scoped>
.roles-page { width: 100%; min-width: 0; }
.toolbar, .assignment-form, .editor-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.role-search { max-width: 320px; margin-bottom: 16px; }
.role-table { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; text-align: left; }
th, td { padding: 12px 16px; border-bottom: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
.grant-summary { display: inline-block; margin-right: 16px; }
h3 { margin: 32px 0 16px; font-size: var(--app-text-xl); }
.assignment-form :deep(.t-select__wrap) { width: 240px; max-width: 100%; }
.hint { color: var(--td-text-color-secondary); line-height: 1.6; }
fieldset { margin: 20px 0; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-sm); min-width: 0; }
.permission-options { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; padding: 8px 0; }
.permission-options :deep(.t-checkbox) { margin: 0; }
.permission-options :deep(.t-checkbox__label) { white-space: normal; overflow-wrap: anywhere; }
.editor-actions { margin-top: 24px; }
</style>
