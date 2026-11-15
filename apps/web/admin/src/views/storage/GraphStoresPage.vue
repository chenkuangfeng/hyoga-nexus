<script setup lang="ts">
/** 企业图存储目录；当前已实现的外部提供方为未验证的 Neo4j。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from '../../stores/context'
import { createEnterpriseGraphStore, deleteEnterpriseGraphStore, listEnterpriseGraphStores, testEnterpriseGraphDraft, testEnterpriseGraphStore, type EnterpriseGraphStore, type GraphStoreEngine } from '@nexus-web/core/api/enterprise-graph-stores'

const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
const tenant = computed(() => String(auth.effectiveTenantId || '')), canManage = computed(() => context.can('enterprise_kbs:manage'))
const rows = ref<EnterpriseGraphStore[]>([]), engines = ref<GraphStoreEngine[]>([]), ready = ref(false), loading = ref(false), busy = ref(false), testing = ref(false), error = ref('')
const editor = ref(false), name = ref(''), url = ref(''), username = ref('neo4j'), password = ref(''), database = ref('neo4j')
const available = computed(() => engines.value.filter(row => row.status === 'available' && !row.builtin)), planned = computed(() => engines.value.filter(row => row.status === 'planned'))
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
function clearDraft() { editor.value = false; name.value = ''; url.value = ''; username.value = 'neo4j'; password.value = ''; database.value = 'neo4j' }
function invalidate() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; engines.value = []; ready.value = false; loading.value = false; busy.value = false; testing.value = false; clearDraft(); error.value = '' }
async function load() {
  const current = ++epoch, scope = tenant.value; rows.value = []; engines.value = []; ready.value = false; error.value = ''
  if (!scope || !canManage.value) return
  loading.value = true
  try { const response = await listEnterpriseGraphStores(scope); if (current === epoch) { rows.value = response.items; engines.value = response.engines; ready.value = true } }
  catch { if (current === epoch) error.value = t('adminGraph.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalidate(); void load() }, { immediate: true })
onBeforeUnmount(invalidate)
function openCreate() { if (!ready.value || busy.value || !canManage.value || !available.value.length) return
  name.value = ''; url.value = ''; username.value = 'neo4j'; password.value = ''; database.value = 'neo4j'; error.value = ''; editor.value = true }
function payload() { return { name: name.value.trim(), engine: available.value[0]?.engine || 'neo4j', connection_config: { url: url.value.trim(), username: username.value.trim(), password: password.value, database: database.value.trim() || 'neo4j' } } }
function valid() { return !!name.value.trim() && !!url.value.trim() && !!username.value.trim() && !!password.value }
async function save() {
  if (!canManage.value || !ready.value || busy.value || testing.value || !valid()) return
  const current = epoch, scope = tenant.value; busy.value = true; error.value = ''
  try { const result = await createEnterpriseGraphStore(scope, payload()); if (current !== epoch || !canManage.value) return
    rows.value = [...rows.value, result]; clearDraft(); MessagePlugin.success(t('adminGraph.created'))
  } catch { if (current === epoch) error.value = t('adminGraph.saveFailed') }
  finally { if (current === epoch) busy.value = false }
}
async function testDraft() {
  if (!canManage.value || !ready.value || busy.value || testing.value || !valid()) return
  const current = epoch, scope = tenant.value; testing.value = true; error.value = ''
  try { const result = await testEnterpriseGraphDraft(scope, payload()); if (current !== epoch) return
    if (result.ok) MessagePlugin.success(t('adminGraph.testOk')); else error.value = result.message || t('adminGraph.testFailed')
  } catch { if (current === epoch) error.value = t('adminGraph.testFailed') }
  finally { if (current === epoch) testing.value = false }
}
async function testSaved(row: EnterpriseGraphStore) {
  if (!canManage.value || !ready.value || busy.value) return
  const current = epoch, scope = tenant.value; busy.value = true; error.value = ''
  try { const result = await testEnterpriseGraphStore(scope, row.id); if (current !== epoch) return
    if (result.ok) MessagePlugin.success(t('adminGraph.testOk')); else error.value = result.message || t('adminGraph.testFailed')
  } catch { if (current === epoch) error.value = t('adminGraph.testFailed') }
  finally { if (current === epoch) busy.value = false }
}
function remove(row: EnterpriseGraphStore) {
  if (!canManage.value || !ready.value || busy.value || row.builtin || confirmation) return
  const current = epoch, scope = tenant.value; let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminGraph.deleteTitle'), body: t('adminGraph.deleteConfirm', { name: row.name }), theme: 'danger', onConfirm: async () => {
    if (confirmation !== dialog) return; dialog.hide(); confirmation = undefined
    if (current !== epoch || !canManage.value || busy.value) return
    busy.value = true; error.value = ''
    try { await deleteEnterpriseGraphStore(scope, row.id); if (current !== epoch) return
      rows.value = rows.value.filter(item => item.id !== row.id); MessagePlugin.success(t('adminGraph.deleted'))
    } catch { if (current === epoch) error.value = t('adminGraph.deleteFailed') }
    finally { if (current === epoch) busy.value = false }
  }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined } })
  confirmation = dialog
}
</script>

<template>
  <section class="graph-page">
    <header class="section-header"><div><h2>{{ t('adminGraph.title') }}</h2><p>{{ t('adminGraph.description') }}</p></div><div class="actions"><t-button theme="primary" :disabled="!ready || busy || !available.length" @click="openCreate"><t-icon name="add" />{{ t('adminGraph.add') }}</t-button><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></div></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminGraph.scopeHint')" />
      <t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading"><div v-if="ready" class="table-shell"><table><thead><tr><th>{{ t('adminGraph.name') }}</th><th>{{ t('adminGraph.engine') }}</th><th>{{ t('adminGraph.kind') }}</th><th>{{ t('adminGraph.actions') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.name }}</td><td>{{ row.engine }}</td><td>{{ t(row.builtin ? 'adminGraph.builtin' : 'adminGraph.custom') }}</td><td><t-button variant="text" :disabled="busy" @click="testSaved(row)">{{ t('adminGraph.test') }}</t-button><t-button v-if="!row.builtin" variant="text" theme="danger" :disabled="busy" @click="remove(row)">{{ t('adminGraph.delete') }}</t-button></td></tr><tr v-if="!rows.length"><td colspan="4">{{ t('adminGraph.empty') }}</td></tr></tbody></table></div></t-loading>
      <section v-if="available.length" class="supported"><h3>{{ t('adminGraph.supported') }}</h3><p v-for="item in available" :key="item.engine">{{ item.name }}<t-tag theme="warning" variant="light">{{ t('adminGraph.unverified') }}</t-tag></p></section>
      <section v-if="planned.length" class="planned"><h3>{{ t('adminGraph.planned') }}</h3><p>{{ planned.map(item => item.name).join('、') }}</p></section>
      <section v-if="editor" class="editor"><header class="section-header"><div><h3>{{ t('adminGraph.register') }}</h3><p>{{ t('adminGraph.formHint') }}</p></div><t-button variant="text" :disabled="busy || testing" @click="clearDraft">{{ t('common.close') }}</t-button></header>
        <div class="fields"><label>{{ t('adminGraph.name') }}<t-input v-model="name" :maxlength="160" :disabled="busy || testing" /></label><label>{{ t('adminGraph.url') }}<t-input v-model="url" placeholder="neo4j+s://host:7687" :disabled="busy || testing" /></label><label>{{ t('adminGraph.username') }}<t-input v-model="username" :disabled="busy || testing" /></label><label>{{ t('adminGraph.password') }}<t-input v-model="password" type="password" :disabled="busy || testing" /></label><label>{{ t('adminGraph.database') }}<t-input v-model="database" :disabled="busy || testing" /></label></div>
        <div class="actions editor-actions"><t-button variant="outline" :loading="testing" :disabled="busy || testing || !valid()" @click="testDraft">{{ t('adminGraph.testDraft') }}</t-button><span class="spacer" /><t-button variant="outline" :disabled="busy || testing" @click="clearDraft">{{ t('common.cancel') }}</t-button><t-button theme="primary" :loading="busy" :disabled="busy || testing || !valid()" @click="save">{{ t('adminGraph.save') }}</t-button></div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.graph-page { min-width: 0; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.table-shell { max-width: 100%; overflow-x: auto; margin-top: 20px; }
table { width: 100%; min-width: 600px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
.supported, .planned, .editor { margin-top: 24px; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.supported p { display: flex; align-items: center; gap: 12px; }
.planned p, .editor p { color: var(--td-text-color-secondary); }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 16px; }
.fields label { display: grid; gap: 8px; min-width: 0; }
.fields :deep(.t-input) { width: 100%; }
.editor-actions { margin-top: 24px; }
.spacer { flex: 1; }
@media (max-width: 600px) { .editor, .planned, .supported { padding: 16px; } }
</style>
