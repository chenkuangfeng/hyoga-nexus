<script setup lang="ts">
/** 管理端审计只展示服务端元数据，未知动作/结果原样保留，不渲染 HTML。 */
import { useI18n } from 'vue-i18n'
import { useAuditAdministration } from './useAuditAdministration'
const { t } = useI18n()
const { loaded, loading, exporting, error, exportError, exported, search, limit, selected, start, end, canRead, validRange, filteredRows, load, download, inspect } = useAuditAdministration()
</script>
<template>
  <section class="audit-page">
    <header class="section-header"><div><h2>{{ t('adminAudit.title') }}</h2><p>{{ t('adminAudit.description') }}</p></div><t-button variant="outline" :loading="loading" @click="load">{{ t('connectionUi.refresh') }}</t-button></header>
    <t-alert v-if="!canRead" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminAudit.scopeHint', { count: limit })" />
      <div class="audit-toolbar"><t-input v-model="search" :aria-label="t('adminAudit.search')" :placeholder="t('adminAudit.search')" clearable /><t-select v-model="limit" :aria-label="t('adminAudit.limit')" :options="[100, 500].map(value => ({ value, label: String(value) }))" /></div>
      <t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading"><div v-if="loaded" class="data-table-shell audit-table"><table><thead><tr><th>{{ t('adminAudit.time') }}</th><th>{{ t('adminAudit.actor') }}</th><th>{{ t('adminAudit.action') }}</th><th>{{ t('adminAudit.target') }}</th><th>{{ t('adminAudit.result') }}</th><th>{{ t('adminAudit.details') }}</th></tr></thead><tbody><tr v-for="row in filteredRows" :key="row.id"><td><time>{{ row.created_at }}</time></td><td>{{ row.actor_user_id || t('adminAudit.system') }}</td><td>{{ row.action }}</td><td>{{ row.target_type }} · {{ row.target_id }}</td><td>{{ row.result }}</td><td><t-button variant="text" @click="inspect(row)">{{ t('adminAudit.details') }}</t-button></td></tr><tr v-if="!filteredRows.length"><td colspan="6">{{ t(search.trim() ? 'adminAudit.noMatch' : 'adminAudit.empty') }}</td></tr></tbody></table></div></t-loading>
      <h3>{{ t('adminAudit.exportTitle') }}</h3><p class="hint">{{ t('adminAudit.exportHint') }}</p>
      <div class="audit-export"><label>{{ t('adminAudit.start') }}<input v-model="start" type="date" :disabled="exporting" /></label><label>{{ t('adminAudit.end') }}<input v-model="end" type="date" :disabled="exporting" /></label><t-button theme="primary" :loading="exporting" :disabled="!validRange || exporting" @click="download">{{ t('adminAudit.export') }}</t-button></div>
      <t-alert v-if="!validRange" theme="warning" :message="t('adminAudit.invalidDates')" /><t-alert v-if="exportError" theme="error" :message="exportError" /><t-alert v-if="exported" theme="success" :message="t('adminAudit.exported')" />
    </template>
    <t-dialog :visible="!!selected" :header="t('adminAudit.details')" :footer="false" width="720px" @close="selected = null"><pre>{{ JSON.stringify(selected?.metadata ?? {}, null, 2) }}</pre></t-dialog>
  </section>
</template>
<style scoped>
.audit-page { width: 100%; min-width: 0; }
.audit-toolbar, .audit-export { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin: 16px 0; }
.audit-toolbar :deep(.t-input__wrap) { width: 320px; max-width: 100%; }
.audit-toolbar :deep(.t-select__wrap) { width: 120px; }
.audit-table { overflow-x: auto; max-width: 100%; }
table { width: 100%; min-width: 900px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
td:first-child { white-space: nowrap; }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
h3 { margin: 32px 0 12px; font-size: var(--app-text-xl); }
.hint { color: var(--td-text-color-secondary); line-height: 1.6; }
label { display: grid; gap: 8px; color: var(--td-text-color-secondary); }
input { font: inherit; color: var(--td-text-color-primary); background: var(--td-bg-color-container); border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-xs); padding: 6px 10px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 60vh; overflow-y: auto; }
</style>
