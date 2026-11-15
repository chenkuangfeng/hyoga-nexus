<script setup lang="ts">
/** 企业向量库注册与连接测试；表单按后端能力字段目录生成。 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next'
import { useAuthStore } from '@nexus-web/core/stores/auth'
import { useAdminContext } from '../../stores/context'
import { createEnterpriseVectorStore, deleteEnterpriseVectorStore, listEnterpriseVectorStores, listEnterpriseVectorTypes, testEnterpriseVectorDraft, testEnterpriseVectorStore, updateEnterpriseVectorStore, type EnterpriseVectorStore, type VectorField, type VectorType } from '@nexus-web/core/api/enterprise-vector-stores'

const { t } = useI18n(), auth = useAuthStore(), context = useAdminContext()
const tenant = computed(() => String(auth.effectiveTenantId || ''))
const canManage = computed(() => context.can('enterprise_kbs:manage'))
const rows = ref<EnterpriseVectorStore[]>([]), types = ref<VectorType[]>([]), ready = ref(false), loading = ref(false), busy = ref(false), error = ref('')
const editor = ref(false), editing = ref<EnterpriseVectorStore | null>(null), name = ref(''), engine = ref(''), connection = ref<Record<string, unknown>>({}), index = ref<Record<string, unknown>>({})
const testing = ref(false)
const selectedType = computed(() => types.value.find(row => row.type === engine.value))
const availableTypes = computed(() => types.value.filter(row => row.status === 'available'))
const plannedTypes = computed(() => types.value.filter(row => row.status === 'planned'))
let epoch = 0, confirmation: ReturnType<typeof DialogPlugin.confirm> | undefined
function invalid() { epoch++; confirmation?.hide(); confirmation = undefined; rows.value = []; types.value = []; ready.value = false; loading.value = false; busy.value = false; editor.value = false; editing.value = null; error.value = '' }
async function load() {
  const current = ++epoch, scope = tenant.value
  rows.value = []; types.value = []; ready.value = false; error.value = ''
  if (!scope || !canManage.value) return
  loading.value = true
  try {
    const [storeRows, typeRows] = await Promise.all([listEnterpriseVectorStores(scope), listEnterpriseVectorTypes(scope)])
    if (current === epoch) { rows.value = storeRows; types.value = typeRows; ready.value = true }
  } catch { if (current === epoch) error.value = t('adminVector.loadFailed') }
  finally { if (current === epoch) loading.value = false }
}
watch(() => `${tenant.value}:${auth.user?.id || ''}:${context.revision}:${canManage.value}`, () => { invalid(); void load() }, { immediate: true })
onBeforeUnmount(invalid)
function valueFor(field: VectorField) { return field.default === undefined ? (field.type === 'boolean' ? false : field.type === 'number' ? undefined : '') : field.default }
function openCreate() {
  if (!ready.value || busy.value || !canManage.value || !availableTypes.value.length) return
  editing.value = null; name.value = ''; engine.value = availableTypes.value[0].type; connection.value = {}; index.value = {}
  for (const field of selectedType.value?.connection_fields || []) connection.value[field.name] = valueFor(field)
  for (const field of selectedType.value?.index_fields || []) index.value[field.name] = valueFor(field)
  editor.value = true
}
function openEdit(row: EnterpriseVectorStore) {
  if (!ready.value || busy.value || !canManage.value || row.builtin || !rows.value.includes(row)) return
  editing.value = row; name.value = row.name; engine.value = row.engine
  connection.value = { ...row.connection_config }; index.value = { ...row.index_config }; editor.value = true
}
function changeEngine(value: unknown) {
  if (editing.value || typeof value !== 'string' || !availableTypes.value.some(row => row.type === value)) return
  engine.value = value; connection.value = {}; index.value = {}
  for (const field of selectedType.value?.connection_fields || []) connection.value[field.name] = valueFor(field)
  for (const field of selectedType.value?.index_fields || []) index.value[field.name] = valueFor(field)
}
function setNumber(target: Record<string, unknown>, field: VectorField, value: unknown) { target[field.name] = typeof value === 'number' && Number.isFinite(value) ? value : undefined }
function fieldLabel(field: VectorField) { return field.description || field.name }
function validForm(): boolean {
  if (!name.value.trim() || !selectedType.value || selectedType.value.status !== 'available') return false
  for (const [fields, values] of [[selectedType.value.connection_fields, connection.value], [selectedType.value.index_fields, index.value]] as const) {
    for (const field of fields) {
      const value = values[field.name]
      if (field.required && (value === undefined || value === null || value === '' || (typeof value === 'string' && !value.trim()))) return false
      if (field.type === 'number' && value !== undefined && value !== null && (typeof value !== 'number' || !Number.isFinite(value) || (field.min !== undefined && value < field.min))) return false
    }
  }
  return true
}
function payload() { return { name: name.value.trim(), engine: engine.value, connection_config: { ...connection.value }, index_config: { ...index.value } } }
async function save() {
  if (!canManage.value || !ready.value || busy.value || !editor.value || !validForm()) return
  const current = epoch, scope = tenant.value, target = editing.value?.id
  busy.value = true; error.value = ''
  try {
    const result = target ? await updateEnterpriseVectorStore(scope, target, { name: name.value.trim(), connection_config: { ...connection.value }, index_config: { ...index.value } }) : await createEnterpriseVectorStore(scope, payload())
    if (current !== epoch || !canManage.value) return
    if (target) rows.value = rows.value.map(row => row.id === target ? result : row); else rows.value = [...rows.value, result]
    editor.value = false; editing.value = null; MessagePlugin.success(t(target ? 'adminVector.updated' : 'adminVector.created'))
  } catch { if (current === epoch) error.value = t('adminVector.saveFailed') }
  finally { if (current === epoch) busy.value = false }
}
async function testDraft() {
  if (!canManage.value || !ready.value || busy.value || !validForm() || editing.value) return
  const current = epoch, scope = tenant.value
  testing.value = true; error.value = ''
  try { const result = await testEnterpriseVectorDraft(scope, payload()); if (current !== epoch) return
    if (result.ok) MessagePlugin.success(t('adminVector.testOk'))
    else error.value = result.message || t('adminVector.testFailed')
  } catch { if (current === epoch) error.value = t('adminVector.testFailed') }
  finally { if (current === epoch) testing.value = false }
}
async function testSaved(row: EnterpriseVectorStore) {
  if (!canManage.value || !ready.value || busy.value) return
  const current = epoch, scope = tenant.value
  busy.value = true; error.value = ''
  try { const result = await testEnterpriseVectorStore(scope, row.id); if (current !== epoch) return
    if (result.ok) MessagePlugin.success(t('adminVector.testOk'))
    else error.value = result.message || t('adminVector.testFailed')
  } catch { if (current === epoch) error.value = t('adminVector.testFailed') }
  finally { if (current === epoch) busy.value = false }
}
function remove(row: EnterpriseVectorStore) {
  if (!canManage.value || !ready.value || busy.value || row.builtin || confirmation) return
  const current = epoch, scope = tenant.value
  let dialog: ReturnType<typeof DialogPlugin.confirm>
  dialog = DialogPlugin.confirm({ header: t('adminVector.deleteTitle'), body: t('adminVector.deleteConfirm', { name: row.name }), theme: 'danger',
    onConfirm: async () => {
      if (confirmation !== dialog) return
      dialog.hide(); confirmation = undefined
      if (current !== epoch || !canManage.value || busy.value) return
      busy.value = true; error.value = ''
      try { await deleteEnterpriseVectorStore(scope, row.id); if (current !== epoch) return
        rows.value = rows.value.filter(item => item.id !== row.id); MessagePlugin.success(t('adminVector.deleted'))
      } catch { if (current === epoch) error.value = t('adminVector.deleteFailed') }
      finally { if (current === epoch) busy.value = false }
    }, onClose: () => { dialog.hide(); if (confirmation === dialog) confirmation = undefined },
  })
  confirmation = dialog
}
</script>

<template>
  <section class="vector-page">
    <header class="section-header"><div><h2>{{ t('adminVector.title') }}</h2><p>{{ t('adminVector.description') }}</p></div><div class="actions"><t-button theme="primary" :disabled="!ready || busy || !availableTypes.length" @click="openCreate"><t-icon name="add" />{{ t('adminVector.add') }}</t-button><t-button variant="outline" :loading="loading" :disabled="busy" @click="load">{{ t('connectionUi.refresh') }}</t-button></div></header>
    <t-alert v-if="!canManage" theme="info" :message="t('adminConsole.denied')" />
    <template v-else>
      <t-alert theme="info" :message="t('adminVector.scopeHint')" />
      <t-alert v-if="error" theme="error" :message="error" />
      <t-loading :loading="loading"><div v-if="ready" class="table-shell"><table><thead><tr><th>{{ t('adminVector.name') }}</th><th>{{ t('adminVector.engine') }}</th><th>{{ t('adminVector.kind') }}</th><th>{{ t('adminVector.actions') }}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.name }}</td><td>{{ row.engine }}</td><td>{{ t(row.builtin ? 'adminVector.builtin' : 'adminVector.custom') }}</td><td><t-button variant="text" :disabled="busy" @click="testSaved(row)">{{ t('adminVector.test') }}</t-button><t-button v-if="!row.builtin" variant="text" :disabled="busy" @click="openEdit(row)">{{ t('adminVector.edit') }}</t-button><t-button v-if="!row.builtin" variant="text" theme="danger" :disabled="busy" @click="remove(row)">{{ t('adminVector.delete') }}</t-button></td></tr><tr v-if="!rows.length"><td colspan="4">{{ t('adminVector.empty') }}</td></tr></tbody></table></div></t-loading>
      <section v-if="plannedTypes.length" class="planned"><h3>{{ t('adminVector.planned') }}</h3><p>{{ plannedTypes.map(row => row.display_name).join('、') }}</p></section>
      <section v-if="editor" class="editor"><header class="section-header"><div><h3>{{ t(editing ? 'adminVector.edit' : 'adminVector.add') }}</h3><p v-if="selectedType && !selectedType.verified">{{ t('adminVector.unverified') }}</p></div><t-button variant="text" :disabled="busy || testing" @click="editor = false">{{ t('common.close') }}</t-button></header>
        <div class="fields"><label>{{ t('adminVector.name') }}<t-input v-model="name" :maxlength="160" :disabled="busy" /></label><label>{{ t('adminVector.engine') }}<t-select :value="engine" :options="availableTypes.map(row => ({ label: row.display_name, value: row.type }))" :disabled="!!editing || busy" @change="changeEngine" /></label></div>
        <h4>{{ t('adminVector.connection') }}</h4><div class="fields"><label v-for="field in selectedType?.connection_fields || []" :key="`c-${field.name}`">{{ fieldLabel(field) }}<t-select v-if="field.enum?.length" v-model="connection[field.name]" :options="field.enum.map(value => ({ label: value, value }))" :disabled="!!editing || busy" /><t-switch v-else-if="field.type === 'boolean'" :value="connection[field.name] === true" :disabled="!!editing || busy" @change="connection[field.name] = $event" /><t-input-number v-else-if="field.type === 'number'" :value="typeof connection[field.name] === 'number' ? connection[field.name] as number : undefined" :min="field.min" :disabled="!!editing || busy" @change="setNumber(connection, field, $event)" /><t-input v-else v-model="connection[field.name]" :type="field.sensitive ? 'password' : 'text'" :disabled="!!editing || busy" :placeholder="field.sensitive ? t('adminVector.secretHint') : ''" /></label><p v-if="!selectedType?.connection_fields.length">{{ t('adminVector.noFields') }}</p></div>
        <h4>{{ t('adminVector.indexConfig') }}</h4><div class="fields"><label v-for="field in selectedType?.index_fields || []" :key="`i-${field.name}`">{{ fieldLabel(field) }}<t-select v-if="field.enum?.length" v-model="index[field.name]" :options="field.enum.map(value => ({ label: value, value }))" :disabled="!!editing || busy" /><t-switch v-else-if="field.type === 'boolean'" :value="index[field.name] === true" :disabled="!!editing || busy" @change="index[field.name] = $event" /><t-input-number v-else-if="field.type === 'number'" :value="typeof index[field.name] === 'number' ? index[field.name] as number : undefined" :min="field.min" :disabled="!!editing || busy" @change="setNumber(index, field, $event)" /><t-input v-else v-model="index[field.name]" :disabled="!!editing || busy" /></label><p v-if="!selectedType?.index_fields.length">{{ t('adminVector.noIndexFields') }}</p></div>
        <div class="actions editor-actions"><t-button v-if="!editing" variant="outline" :loading="testing" :disabled="busy || testing || !validForm()" @click="testDraft">{{ t('adminVector.testDraft') }}</t-button><span class="spacer" /><t-button variant="outline" :disabled="busy || testing" @click="editor = false">{{ t('common.cancel') }}</t-button><t-button theme="primary" :loading="busy" :disabled="busy || testing || !validForm()" @click="save">{{ t('common.save') }}</t-button></div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.vector-page { min-width: 0; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.table-shell { max-width: 100%; overflow-x: auto; margin-top: 20px; }
table { width: 100%; min-width: 620px; border-collapse: collapse; text-align: left; }
th, td { padding: 12px; border-bottom: 1px solid var(--td-component-stroke); }
th { background: var(--td-bg-color-secondarycontainer); font-weight: 500; }
.planned, .editor { margin-top: 24px; padding: 20px; border: 1px solid var(--td-component-stroke); border-radius: var(--app-radius-lg); background: var(--td-bg-color-container); }
.planned p, .editor p { color: var(--td-text-color-secondary); }
.editor h4 { margin: 24px 0 12px; }
.fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 16px; }
.fields label { display: grid; gap: 8px; min-width: 0; }
.fields :deep(.t-input), .fields :deep(.t-select), .fields :deep(.t-input-number) { width: 100%; }
.editor-actions { margin-top: 24px; }
.spacer { flex: 1; }
@media (max-width: 600px) { .editor, .planned { padding: 16px; } .section-header { align-items: flex-start; gap: 12px; } }
</style>
